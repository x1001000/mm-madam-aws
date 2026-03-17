from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Literal, Optional, Dict, Any
from google import genai
from google.genai import types
import csv
# Increase CSV field size limit to handle large podcast transcripts
import sys
csv.field_size_limit(sys.maxsize)
import json
import glob
import requests
import re
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pprint import pprint
import traceback
import threading
import asyncio
import httpx
import jwt
import markdown
# Enable the tables extension
md = markdown.Markdown(extensions=['tables', 'nl2br'])
from markdownify import markdownify

from dotenv import load_dotenv
load_dotenv()
# GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
SEARCH_API_KEY = os.getenv('SEARCH_API_KEY')
SYSTEM_PROMPT_URL = os.getenv('SYSTEM_PROMPT_URL')
MARKETING_PROMPT_URL = os.getenv('MARKETING_PROMPT_URL')
KNOWLEDGE_CSV_API = os.getenv('KNOWLEDGE_CSV_API')
CHARTS_DATA_API = os.getenv('CHARTS_DATA_API')
PODCAST_FOLDER_URL = os.getenv('PODCAST_FOLDER_URL')
GITHUB_GIST_API = os.getenv('GITHUB_GIST_API')
GITHUB_ACCESS_TOKEN = os.getenv('GITHUB_ACCESS_TOKEN')
LOGGER = os.getenv('LOGGER')
JWT_SECRET = os.getenv('JWT_SECRET')
USAGE_API = os.getenv('USAGE_API')
USAGE_LIMITS_URL = os.getenv('USAGE_LIMITS_URL')
MCP_USER_ID = 101001000
TAIPEI_OFFSET = 8
PERIOD_MAP = {'day': 'daily', 'week': 'weekly', 'month': 'monthly'}
USAGE_LIMITS_DEFAULT = {
    'FREE': {'CUSTOMER_SERVICE': (10, 'weekly'), 'MACROECONOMICS': (0, 'monthly')},
    'PAID': {'CUSTOMER_SERVICE': (10, 'weekly'), 'MACROECONOMICS': (5, 'monthly')},
}


TTL_CACHE = {}
TTL_SECONDS = 300  # 5 minutes


def ttl_cached(key, fetcher):
    """Return cached value for key, refreshing via fetcher() if older than TTL."""
    now = time.time()
    entry = TTL_CACHE.get(key)
    if not entry or now - entry['t'] > TTL_SECONDS:
        TTL_CACHE[key] = {'data': fetcher(), 't': now}
    return TTL_CACHE[key]['data']


def fetch_usage_limits():
    """Fetch USAGE_LIMITS from Google Sheet CSV. Falls back to default on error."""
    if not USAGE_LIMITS_URL:
        return USAGE_LIMITS_DEFAULT
    try:
        resp = requests.get(USAGE_LIMITS_URL, timeout=10)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        reader = csv.reader(resp.text.strip().splitlines())
        header = next(reader)  # e.g. ['', 'CUSTOMER_SERVICE', 'MACROECONOMICS']
        question_types = header[1:]
        limits = {}
        for row in reader:
            role = row[0].strip()  # e.g. 'FREE', 'PAID'
            role_limits = {}
            for i, cell in enumerate(row[1:], start=0):
                cell = cell.strip()
                if not cell:
                    continue
                count, period_key = cell.split('/')
                period = PERIOD_MAP.get(period_key, period_key)
                role_limits[question_types[i]] = (int(count), period)
            if role_limits:
                limits[role] = role_limits
        print(f"USAGE_LIMITS loaded from Google Sheet: {limits}")
        return limits
    except Exception as e:
        print(f"Failed to fetch USAGE_LIMITS, using default: {e}")
        return USAGE_LIMITS_DEFAULT


def get_usage_limits():
    return ttl_cached('usage_limits', fetch_usage_limits)

app = FastAPI(title="MM Madam API", version="1.0.0")

# Enable CORS for website integration
origins = [
    "https://debug.macromicro.me",
    "https://debug-sc.macromicro.me",
    "https://debug-en.macromicro.me",
    "https://dev.macromicro.me",
    "https://dev-sc.macromicro.me",
    "https://dev-en.macromicro.me",
    "https://www.macromicro.me",
    "https://sc.macromicro.me",
    "https://en.macromicro.me",
    "https://debug-cms.macromicro.me",
    "https://dev-cms.macromicro.me",
    "https://cms.macromicro.me",
    "https://dev-madam-chat.macromicro.me",
    "https://madam-chat.macromicro.me",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (test frontend only, guarded by ENABLE_FRONTEND)
if os.getenv("ENABLE_FRONTEND", "false").lower() == "true":
    app.mount("/static", StaticFiles(directory="test-frontend"), name="static")

# automatically set to 20 days ago
AFTER_DATE = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
# manually update
PRICING = {
    'gemini-3-flash-preview': {'input': 0.5, 'output': 3, 'thinking': 3, 'caching': 0.05},
    'gemini-3.1-pro-preview': {'input': 2, 'output': 12, 'thinking': 12, 'caching': 0.2},
}
DEFAULT_MODEL = 'gemini-3-flash-preview'

LANG_TO_SUBDOMAIN = {'tc': 'www', 'sc': 'sc', 'en': 'en'}
LANG_TO_ROUTE = {'tc': 'zh-tw', 'sc': 'zh-cn', 'en': 'en-001'}
LANG_TO_CX = {'tc': '414d6323cec6d419d', 'sc': '75b3a0dc17f00410a', 'en': 'c5e06c51ebc924baf'}


# Request/Response models
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    user_id: Optional[int] = None  # backward compatible
    message: str
    jwt: Optional[str] = None  # optional for mm-mcp-aws, mm-chatgpt-app
    conversation_history: Optional[List[ChatMessage]] = []
    config: Optional[Dict[str, Any]] = {}
    response_type: Optional[str] = 'html'
    current_page_html: Optional[str] = None  # text content of the page where chat bubble is used
    current_page_url: Optional[str] = None  # URL of the page where chat bubble is used (for logging)
    lang: str = 'tc'


class ChatResponse(BaseModel):
    response_html: str
    response_markdown: str
    cost: float
    token_usage: Dict[str, int]
    conversation_history: List[ChatMessage]
    response_seconds: float
    started: int
    requested: int
    responded: int


class ConfigModel(BaseModel):
    is_paid_user: bool = True
    has_chart: bool = True
    has_quickie: bool = True
    has_blog: bool = True
    has_edm: bool = True
    has_podcast: bool = True
    has_google_search: bool = True
    has_help_center: bool = True
    conversation_rounds: int = 2
    thinking_budget: int = 500
    quality_model: str = DEFAULT_MODEL
    N_most_relevant: int = 5
    no_single_series: bool = False


class SearchRequest(BaseModel):
    query: str
    jwt: Optional[str] = None
    lang: str = 'tc'


class SearchResponse(BaseModel):
    results: str


class SystemPromptRequest(BaseModel):
    message: str
    config: Optional[Dict[str, Any]] = {}


class SystemPromptResponse(BaseModel):
    system_prompt: str

# Global variables for token counting and system prompt storage
last_system_prompt = ""
user_sessions = {}  # Track session start times by user_id
user_conversation_histories = {}  # Store conversation history by user_id


class TokenCounter:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self.prompt_token_count = 0
        self.candidates_token_count = 0
        self.cached_content_token_count = 0
        self.thoughts_token_count = 0
        self.tool_use_prompt_token_count = 0
        self.total_token_count = 0
        self.costs_by_model = {}

    def accumulate(self, usage_metadata, model):
        with self._lock:
            self.prompt_token_count += usage_metadata.prompt_token_count
            self.candidates_token_count += usage_metadata.candidates_token_count
            self.cached_content_token_count += usage_metadata.cached_content_token_count or 0
            self.thoughts_token_count += usage_metadata.thoughts_token_count or 0
            self.tool_use_prompt_token_count += usage_metadata.tool_use_prompt_token_count or 0
            self.total_token_count += usage_metadata.total_token_count

            # Calculate cost for this specific model call
            if model in PRICING:
                call_cost = (
                    usage_metadata.prompt_token_count * PRICING[model]['input'] +
                    usage_metadata.candidates_token_count * PRICING[model]['output'] +
                    (usage_metadata.cached_content_token_count or 0) * PRICING[model]['caching'] +
                    (usage_metadata.thoughts_token_count or 0) * PRICING[model]['thinking']) / 1e6

                if model not in self.costs_by_model:
                    self.costs_by_model[model] = 0
                self.costs_by_model[model] += call_cost
    
    def total_cost(self):
        return round(sum(self.costs_by_model.values()), 3)
    
    def cost(self, model):
        # Legacy method for backward compatibility - returns total cost
        return self.total_cost()

client = genai.Client()


def fetch_base_system_prompt():
    text = requests.get(SYSTEM_PROMPT_URL).text
    parts = re.split(r'^# .+\n', text, flags=re.MULTILINE)
    # parts[0] is empty (before first heading), tabs are parts[1], [2], [3]
    return parts[1].strip(), parts[2].strip(), parts[3].strip()  # system_prompt, for_paid_user, for_free_user


def get_base_system_prompt():
    return ttl_cached('system_prompt', fetch_base_system_prompt)


def fetch_marketing_prompts():
    text = requests.get(MARKETING_PROMPT_URL).text
    parts = re.split(r'^# .+\n', text, flags=re.MULTILINE)
    # parts[0] is empty (before first heading), tab 1 (www/sc) is parts[1], tab 2 (en) is parts[2]
    return parts[1].strip(), parts[2].strip()


def get_marketing_prompt(lang='tc'):
    prompts = ttl_cached('marketing_prompt', fetch_marketing_prompts)
    return prompts[1] if lang == 'en' else prompts[0]


@lru_cache(maxsize=1)  # heavy operation (downloads podcasts + CSVs), keep cold-start-only
def get_knowledge():
    knowledge = {}
    try:
        # create podcast.csv from podcast transcripts in PODCAST_FOLDER_URL
        import gdown
        gdown.download_folder(PODCAST_FOLDER_URL, output='/tmp/')

        # Find the MM AI folder
        mm_ai_folders = glob.glob('/tmp/MM AI*')
        if mm_ai_folders:
            mm_ai_folder = mm_ai_folders[0]
            podcast_data = []

            # Find all transcript files
            transcript_files = [f for f in glob.glob(f'{mm_ai_folder}/*') if os.path.isfile(f)]

            for transcript_file in transcript_files:
                filename = os.path.basename(transcript_file)
                print(f"Processing transcript file: {filename}")
                # Parse filename: YYMMDD_..._title
                # ID is left of first underscore, title is right of last underscore
                if '_' in filename:
                    first_underscore = filename.index('_')
                    last_underscore = filename.rindex('_')
                    yymmdd = filename[:first_underscore]
                    title = filename[last_underscore+1:]

                    # Validate YYMMDD format
                    if len(yymmdd) == 6 and yymmdd.isdigit():
                        # Convert YYMMDD to 20YY-MM-DD
                        yy, mm, dd = yymmdd[:2], yymmdd[2:4], yymmdd[4:6]
                        date = f'20{yy}-{mm}-{dd}'

                        # Read markdown content
                        try:
                            with open(transcript_file, 'r', encoding='utf-8') as f:
                                markdown_content = f.read()

                            # Strip base64 image references to save tokens
                            markdown_content = re.sub(r'^\[image\d+\]: <data:image[^\n]*\n?', '', markdown_content, flags=re.MULTILINE)

                            podcast_data.append({
                                'id': yymmdd,
                                'title': title,
                                'date': date,
                                'markdown': markdown_content
                            })
                        except Exception as e:
                            print(f"Warning: Could not read {transcript_file}: {e}")

            # Write podcast.csv
            if podcast_data:
                with open('/tmp/podcast.csv', 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['id', 'title', 'date', 'markdown'])
                    writer.writeheader()
                    writer.writerows(podcast_data)
                print(f"Created podcast.csv with {len(podcast_data)} transcripts")

    except Exception as e:
        print(f"Error loading podcasts: {e}")

    # Local CSV files
    local_csv_files = glob.glob('knowledge/*/*/_log.csv')
    if os.path.exists('/tmp/podcast.csv'):
        local_csv_files.append('/tmp/podcast.csv')

    # Remote CSV files
    remote_csv_files = [
        f'{KNOWLEDGE_CSV_API}/chart_tc.csv',
        f'{KNOWLEDGE_CSV_API}/quickie.csv',
        f'{KNOWLEDGE_CSV_API}/post.csv',
        f'{KNOWLEDGE_CSV_API}/post_en.csv',
        f'{KNOWLEDGE_CSV_API}/edm.csv',
    ]

    # Fetch all remote CSVs synchronously (asyncio.run() fails inside Lambda's event loop)
    remote_csv_data = {}
    with httpx.Client() as client:
        for url in remote_csv_files:
            try:
                r = client.get(url)
                remote_csv_data[url] = r.text
            except Exception as e:
                print(f"Warning: Could not fetch {url}: {e}")

    csv_files = local_csv_files + [url for url in remote_csv_files if url in remote_csv_data]

    for csv_file in csv_files:
        try:
            # Read CSV data using native csv module
            if csv_file.startswith('http'):
                lines = remote_csv_data[csv_file].splitlines()
                reader = csv.DictReader(lines)
                data = list(reader)
                print(f"Loaded remote CSV file: {csv_file} with {len(data)} rows")
            else:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    data = list(reader)

            # Filter by date if date column exists
            if data and 'date' in data[0]:
                data = [row for row in data if row['date'] > AFTER_DATE]

            # Extract key: remove 'knowledge/', '/tmp/', or 'csv/' prefixes
            csv_file_key = csv_file.split('knowledge/')[-1].split('/tmp/')[-1].split('csv/')[-1]
            if '/' in csv_file_key:
                global cutoff
                cutoff, lang_route_csv = csv_file_key.split('/', maxsplit=1)
                csv_file_key = f'hc/{lang_route_csv}'
            knowledge[csv_file_key] = data

            # Create first 2 columns JSON equivalent
            if data:
                first_cols = list(data[0].keys())[:2]
                first_two_cols = [{col: row[col] for col in first_cols if col in row} for row in data]
                knowledge[csv_file_key + '=>df.iloc[:,:2].to_json'] = json.dumps(first_two_cols, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not load {csv_file}: {e}")
            continue
    print(f"Knowledge loaded successfully!\n{knowledge.keys()}")

    return knowledge
knowledge = get_knowledge()


def generate_content(contents, system_prompt, response_type, response_schema, tools, token_counter, model=DEFAULT_MODEL, thinking_config=types.ThinkingConfig(thinking_budget=0)):
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type=response_type,
            response_schema=response_schema,
            tools=tools,
            thinking_config=thinking_config,
        )
    )
    print(f'{model} in {sys._getframe(1).f_code.co_name}')
    # pprint(response.usage_metadata)
    token_counter.accumulate(response.usage_metadata, model)
    return response


async def generate_content_async(contents, system_prompt, response_type, response_schema, tools, token_counter, model=DEFAULT_MODEL, thinking_config=types.ThinkingConfig(thinking_budget=0)):
    try:
        # Create fresh client to avoid "Event loop is closed" error on subsequent requests
        async_client = genai.Client()
        response = await async_client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type=response_type,
                response_schema=response_schema,
                tools=tools,
                thinking_config=thinking_config,
            )
        )
        token_counter.accumulate(response.usage_metadata, model)
        return response
    except Exception as e:
        print(f'[async] generate_content_async error: {e}')
        raise


async def generate_content_stream(contents, system_prompt, token_counter, model=DEFAULT_MODEL, thinking_config=types.ThinkingConfig(thinking_budget=0)):
    async_client = genai.Client()
    last_usage = None
    async for chunk in await async_client.aio.models.generate_content_stream(
        model=model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type='text/plain',
            thinking_config=thinking_config,
        )
    ):
        if chunk.usage_metadata:
            last_usage = chunk.usage_metadata
        if chunk.text:
            yield chunk.text
    if last_usage:
        token_counter.accumulate(last_usage, model)


def get_user_prompt_type(contents, token_counter):
    system_prompt = '用戶訊息分類：總經財經市場新聞時事相關問題、網站功能操作客服或其他問題，以 MACROECONOMICS、CUSTOMER_SERVICE 二選一回傳'
    response_type = 'application/json'
    response_schema = Literal['MACROECONOMICS', 'CUSTOMER_SERVICE']
    tools = None
    try:
        response_parsed = generate_content(contents, system_prompt, response_type, response_schema, tools, token_counter).parsed
        print(response_parsed)
        return response_parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Type detection error: {e}")


def get_user_language_code(user_prompt, token_counter):
    system_prompt = 'Given a user query, identify its language code. For Chinese, always return zh-tw for Traditional Chinese or zh-cn for Simplified Chinese, never just zh.'
    response_type = 'application/json'
    response_schema = str
    tools = None
    try:
        return generate_content(user_prompt, system_prompt, response_type, response_schema, tools, token_counter).parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Language detection error: {e}")


def get_most_relevant_ids(csv_df_json, user_prompt, knowledge, token_counter, N_most_relevant):
    system_prompt = f'Given a user query, identify up to {N_most_relevant} of the most relevant IDs in the JSON below.\n'
    system_prompt += knowledge.get(csv_df_json, '') # in case data filtered out AFTER_DATE
    response_type = 'application/json'
    response_schema = list[int]
    tools = None
    try:
        response_parsed = generate_content(user_prompt, system_prompt, response_type, response_schema, tools, token_counter).parsed
        return response_parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ID retrieval error: {e}")


# Async versions of retrieval functions for parallel execution
async def get_user_language_code_async(user_prompt, token_counter):
    system_prompt = 'Given a user query, identify its language code. For Chinese, always return zh-tw for Traditional Chinese or zh-cn for Simplified Chinese, never just zh.'
    response_type = 'application/json'
    response_schema = str
    tools = None
    try:
        response = await generate_content_async(user_prompt, system_prompt, response_type, response_schema, tools, token_counter)
        print(f"[async] get_user_language_code_async got: {response.parsed}")
        return response.parsed
    except Exception as e:
        print(f"[async] get_user_language_code_async error: {e}")
        raise HTTPException(status_code=500, detail=f"Language detection error: {e}")


async def get_most_relevant_ids_async(csv_df_json, user_prompt, knowledge, token_counter, N_most_relevant):
    system_prompt = f'Given a user query, identify up to {N_most_relevant} of the most relevant IDs in the JSON below.\n'
    system_prompt += knowledge.get(csv_df_json, '')
    response_type = 'application/json'
    response_schema = list[int]
    tools = None
    try:
        response = await generate_content_async(user_prompt, system_prompt, response_type, response_schema, tools, token_counter)
        return response.parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ID retrieval error: {e}")


async def get_retrieval_async(csv_file, user_prompt, knowledge, token_counter, N_most_relevant):
    try:
        ids = await get_most_relevant_ids_async(csv_file + '=>df.iloc[:,:2].to_json', user_prompt, knowledge, token_counter, N_most_relevant)
        print(f"[async] get_retrieval_async({csv_file}) got ids: {ids}")
        if ids:
            data = knowledge[csv_file]
            filtered_data = [row for row in data if int(row.get('id', 0)) in ids]
            return json.dumps(filtered_data, ensure_ascii=False), ids
        return None, []
    except Exception as e:
        print(f"[async] get_retrieval_async({csv_file}) error: {e}")
        raise


async def get_retrieval_from_charts_data_api_async(csv_file, user_prompt, knowledge, token_counter, http_client, N_most_relevant, no_single_series):
    try:
        ids = await get_most_relevant_ids_async(csv_file + '=>df.iloc[:,:2].to_json', user_prompt, knowledge, token_counter, N_most_relevant)
        print(f"[async] get_retrieval_from_charts_data_api_async({csv_file}) got ids: {ids}")
        if ids:
            # Fetch all chart data in parallel using httpx
            async def fetch_chart(chart_id):
                r = await http_client.get(f'{CHARTS_DATA_API}/{chart_id}')
                return r.json()

            tasks = [fetch_chart(_id) for _id in ids]
            results = await asyncio.gather(*tasks)

            data = []
            for _id, d in zip(ids, results):
                d['data'][f'c:{_id}']['id'] = d['data'][f'c:{_id}']['info']['id']
                d['data'][f'c:{_id}']['slug'] = d['data'][f'c:{_id}']['info']['slug']
                d['data'][f'c:{_id}']['name_tc'] = d['data'][f'c:{_id}']['info']['name_tc']
                d['data'][f'c:{_id}']['description_tc'] = d['data'][f'c:{_id}']['info']['description_tc']
                series_names = [series_config['name_tc'] for series_config in d['data'][f'c:{_id}']['info']['chart_config']['seriesConfigs']]
                if no_single_series and len(series_names) == 1:
                    continue
                series = d['data'][f'c:{_id}']['series']
                for i in range(len(series)):
                    series[i] = series[i][-2:]
                d['data'][f'c:{_id}']['series'] = dict(zip(series_names, series))
                del d['data'][f'c:{_id}']['info']
                data.append(d['data'][f'c:{_id}'])
            return json.dumps(data, ensure_ascii=False), ids
        return None, []
    except Exception as e:
        print(f"[async] get_retrieval_from_charts_data_api_async({csv_file}) error: {e}")
        raise


async def get_retrieval_from_google_search_async(user_prompt, token_counter):
    system_prompt = None
    response_type = 'text/plain'
    response_schema = None
    tools = [types.Tool(google_search=types.GoogleSearch())]
    try:
        response = await generate_content_async(user_prompt, system_prompt, response_type, response_schema, tools, token_counter)
        response_text = response.text
        web_search_queries = response.candidates[0].grounding_metadata.web_search_queries
        print(f"[async] get_retrieval_from_google_search_async got {len(response_text)} chars, queries: {web_search_queries}")
        return response_text, list(web_search_queries) if web_search_queries else []
    except Exception as e:
        print(f"[async] get_retrieval_from_google_search_async error: {e}")
        raise HTTPException(status_code=500, detail=f"Google search error: {e}")


def get_retrieval_from_help_center(csv_file, user_prompt, knowledge, token_counter, N_most_relevant):
    if ids := get_most_relevant_ids(csv_file + '=>df.iloc[:,:2].to_json', user_prompt, knowledge, token_counter, N_most_relevant):
        # Create list of dictionaries instead of DataFrame
        data = []
        for _id in ids:
            with open(f'knowledge/{cutoff}' + csv_file.replace('hc', '').replace('_log', str(_id)).replace('csv', 'html')) as f:
                html_content = ''.join(f.readlines())
            data.append({'id': _id, 'markdown': markdownify(html_content)})
        return json.dumps(data, ensure_ascii=False), ids
    return None, []


def google_search_site(query, lang='tc'):
    results = []
    search_label = {'tc': '全站搜尋', 'sc': '全站搜寻', 'en': 'Search All'}.get(lang, '全站搜尋')
    try:
        cx = LANG_TO_CX.get(lang, LANG_TO_CX['tc'])
        r = requests.get(f"https://www.googleapis.com/customsearch/v1?key={SEARCH_API_KEY}&cx={cx}&q={query}")
        d = r.json()
        items = d.get('items', [])
        for item in items:
            print(item["title"])
            print(item["link"])
            # Skip items with '用戶圖表' or '用户图表' or 'UGC Charts' in title
            if '用戶圖表' in item["title"] or '用户图表' in item["title"] or 'UGC Charts' in item["title"]:
                continue
            if '/series' in item["link"]:
                results.append(f'📈 [{item["title"]}]({item["link"]})')
            if '/charts' in item["link"]:
                results.append(f'📊 [{item["title"]}]({item["link"]})')
            if '/blog' in item["link"]:
                results.append(f'📝 [{item["title"]}]({item["link"]})')
        results = sorted(results[:6]) # first 6 results sorted in 📈 📊 📝 order
        subdomain = LANG_TO_SUBDOMAIN.get(lang, 'www')
        results.append(f'🔍 [{search_label}](https://{subdomain}.macromicro.me/search?q={query})')
        return '\n\n'.join(results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google site search error: {e}")


async def build_system_prompt(user_prompt_type, contents, config, knowledge, token_counter, lang='tc'):
    """Build the system prompt based on user input and configuration (async version with parallel API calls)"""
    # Initialize tracking variables
    web_search_queries = []
    retrieval_ids = {}
    
    user_prompt = contents[-1]
    N_most_relevant = config.N_most_relevant
    no_single_series = config.no_single_series

    # Get base system prompt (cached)
    system_prompt, for_paid_user, for_free_user = get_base_system_prompt()

    # Determine subdomain based on site language choice
    SUBDOMAIN = LANG_TO_SUBDOMAIN[lang]
    system_prompt += f"\n- SUBDOMAIN == '{SUBDOMAIN}'"

    # For non-financial queries, use the original sequential approach
    if user_prompt_type == 'CUSTOMER_SERVICE':
        # Detect language (single API call, no need for parallelization)
        user_language_code = get_user_language_code(user_prompt, token_counter)
        system_prompt += f"\n- Regardless of SUBDOMAIN, you MUST respond in user_language_code:='{user_language_code}'"

        if config.has_help_center:
            lang_route = LANG_TO_ROUTE[lang]
            system_prompt += f'\n- MM幫助中心網址 https://support.macromicro.me/hc/{lang_route}'
            system_prompt += '\n- 切勿提供來信或來電的客服聯繫方式'
            retrieval, ids = get_retrieval_from_help_center(f'hc/{lang_route}/_log.csv', user_prompt, knowledge, token_counter, N_most_relevant)
            if retrieval:
                retrieval_ids['help_center'] = ids
                system_prompt += '\n- MM幫助中心的相關資料'
                system_prompt += f'（hyperlink pattern: https://support.macromicro.me/hc/{lang_route}/articles/{{id}}）'
                system_prompt += f'\n```\n{retrieval}\n```\n'
        system_prompt += '\n- 若非網站功能操作及客服相關問題，你會婉拒回答'
        system_prompt += '\n\n---\n' + get_marketing_prompt(lang)

        return system_prompt, user_language_code, web_search_queries, retrieval_ids

    # For financial queries, use parallel API calls
    async with httpx.AsyncClient() as http_client:
        # Build task dictionary based on config conditions
        tasks = {}

        # Always need language detection
        tasks['language'] = get_user_language_code_async(user_prompt, token_counter)

        # Add retrieval tasks based on config
        if config.has_chart and config.is_paid_user:
            tasks['chart'] = get_retrieval_from_charts_data_api_async('chart_tc.csv', user_prompt, knowledge, token_counter, http_client, N_most_relevant, no_single_series)

        if config.has_quickie and config.is_paid_user:
            tasks['quickie'] = get_retrieval_async('quickie.csv', user_prompt, knowledge, token_counter, N_most_relevant)

        if config.has_blog and config.is_paid_user:
            tasks['post'] = get_retrieval_async('post.csv', user_prompt, knowledge, token_counter, N_most_relevant)
            tasks['post_en'] = get_retrieval_async('post_en.csv', user_prompt, knowledge, token_counter, N_most_relevant)

        if config.has_edm and config.is_paid_user:
            tasks['edm'] = get_retrieval_async('edm.csv', user_prompt, knowledge, token_counter, N_most_relevant)

        if config.has_podcast and config.is_paid_user:
            tasks['podcast'] = get_retrieval_async('podcast.csv', user_prompt, knowledge, token_counter, N_most_relevant)

        if config.has_google_search and config.is_paid_user:
            tasks['google_search'] = get_retrieval_from_google_search_async(user_prompt, token_counter)

        # Execute all tasks in parallel
        task_keys = list(tasks.keys())
        task_coroutines = list(tasks.values())
        print(f"[async] Executing {len(task_keys)} tasks in parallel: {task_keys}")
        results = await asyncio.gather(*task_coroutines, return_exceptions=True)

        # Map results back to keys
        results_dict = dict(zip(task_keys, results))

        # Debug: print any exceptions
        for key, result in results_dict.items():
            if isinstance(result, Exception):
                print(f"[async] Task '{key}' failed with error: {result}")

    # Process language result
    user_language_code = results_dict.get('language')
    system_prompt += f"\n- Regardless of SUBDOMAIN, you MUST respond in user_language_code:='{user_language_code}'"

    if config.is_paid_user:
        system_prompt += f'\n{for_paid_user}\n'
    else:
        system_prompt += f'\n{for_free_user}\n'

    # Process chart retrieval
    if 'chart' in results_dict and not isinstance(results_dict['chart'], Exception):
        retrieval, ids = results_dict['chart']
        if retrieval:
            retrieval_ids['chart_tc'] = ids
            system_prompt += '\n- MM圖表的相關資料，當中時間序列（series）包含前值及最新數據，務必引用，並將文字或數據超連結至：'
            system_prompt += f'https://{SUBDOMAIN}.macromicro.me/charts/{{id}}/{{slug}}'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    # Process quickie retrieval
    if 'quickie' in results_dict and not isinstance(results_dict['quickie'], Exception):
        retrieval, ids = results_dict['quickie']
        if retrieval:
            retrieval_ids['quickie'] = ids
            system_prompt += '\n- MM短評的相關資料'
            if SUBDOMAIN == 'en':
                system_prompt += '，可引用，但不可提供超連結'
            else:
                system_prompt += f'（hyperlink pattern: https://{SUBDOMAIN}.macromicro.me/quickie?id={{id}}）'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    # Process post retrieval
    if 'post' in results_dict and not isinstance(results_dict['post'], Exception):
        retrieval, ids = results_dict['post']
        if retrieval:
            retrieval_ids['post'] = ids
            system_prompt += '\n- MM中文部落格的相關資料'
            if SUBDOMAIN == 'en':
                system_prompt += '，可引用，但不可提供超連結'
            else:
                system_prompt += f'（hyperlink pattern: https://{SUBDOMAIN}.macromicro.me/blog/{{slug}}）'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    # Process post_en retrieval
    if 'post_en' in results_dict and not isinstance(results_dict['post_en'], Exception):
        retrieval, ids = results_dict['post_en']
        if retrieval:
            retrieval_ids['post_en'] = ids
            system_prompt += '\n- MM英文部落格的相關資料'
            system_prompt += f'（hyperlink pattern: https://en.macromicro.me/blog/{{slug}}）'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    # Process edm retrieval
    if 'edm' in results_dict and not isinstance(results_dict['edm'], Exception):
        retrieval, ids = results_dict['edm']
        if retrieval:
            retrieval_ids['edm'] = ids
            system_prompt += '\n- MM獨家報告的相關資料'
            system_prompt += '，可引用，但不可提供超連結'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    # Process podcast retrieval
    if 'podcast' in results_dict and not isinstance(results_dict['podcast'], Exception):
        retrieval, ids = results_dict['podcast']
        if retrieval:
            retrieval_ids['podcast'] = ids
            system_prompt += '\n- MM Podcast的相關資料'
            system_prompt += '，可引用，但不可提供超連結'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    # Process google search retrieval
    if 'google_search' in results_dict and not isinstance(results_dict['google_search'], Exception):
        result = results_dict['google_search']
        if result[0]:  # Check if retrieval text exists
            retrieval, queries = result
            web_search_queries.extend(queries)
            system_prompt += '\n- 網路搜尋的相關資料'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    return system_prompt, user_language_code, web_search_queries, retrieval_ids


def convert_to_html(response_text):
    """Convert markdown response to HTML with responsive images and target=_blank links"""
    response_html = md.convert(response_text)
    response_html = response_html.replace('<img ', '<img style="max-width: 100%; height: auto;" ')
    response_html = response_html.replace('<a href=', '<a target="_blank" rel="noopener noreferrer" href=')
    return response_html


def get_role_category(role):
    """Classify user into 'BIZ', 'FREE', or 'PAID' based on JWT role."""
    if role == 'FREE':
        return 'FREE'
    if role.startswith('BIZ'):
        return 'BIZ'
    return 'PAID'


def get_usage_period(period):
    """Compute (start_at, end_at) Unix timestamps in Taipei time for the given period."""
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)
    taipei_tz = timezone(timedelta(hours=TAIPEI_OFFSET))
    now_taipei = now_utc.astimezone(taipei_tz)
    end_at = int(now_taipei.timestamp())

    if period == 'daily':
        start = now_taipei.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'weekly':
        days_since_monday = now_taipei.weekday()
        start = (now_taipei - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'monthly':
        start = now_taipei.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now_taipei.replace(hour=0, minute=0, second=0, microsecond=0)

    start_at = int(start.timestamp())
    return start_at, end_at


async def check_usage_limits(user_id, question_type, role_category):
    """Check usage limits against the external usage API.
    Returns None if OK, or a list of exceeded limits if over quota.
    Fails open on API errors.
    """
    if role_category == 'BIZ':
        return None

    limits = get_usage_limits().get(role_category, {})
    limit_entry = limits.get(question_type)
    if not limit_entry:
        return None

    max_count, period = limit_entry
    if max_count == 0:
        return [{'question_type': question_type, 'usage': 0, 'limit': 0, 'period': period}]
    start_at, end_at = get_usage_period(period)

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(USAGE_API, json={
                'user_id': user_id,
                'question_type': question_type,
                'start_at': start_at,
                'end_at': end_at,
            })
            resp.raise_for_status()
            data = resp.json()
            count = data.get('count', 0)
            if count >= max_count:
                return [{'question_type': question_type, 'usage': count, 'limit': max_count, 'period': period}]
    except Exception as e:
        print(f"Usage API error (failing open): {e}")
        return None

    return None


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, request_obj: Request):
    """Main chat endpoint"""
    # Verify JWT: prefer Authorization header, fall back to body
    try:
        config = ConfigModel(**request.config) if request.config else ConfigModel()
        user_role = ''
        if request.user_id != MCP_USER_ID:
            authorization = request_obj.headers.get("authorization", "")
            if authorization.startswith("Bearer "):
                token = authorization[7:]
            elif request.jwt:
                token = request.jwt
            else:
                raise jwt.InvalidTokenError("JWT token required")
            decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience="macromicro.me")
            print(f"JWT decoded successfully: {decoded}")
            request.user_id = int(decoded.get('sub'))
            user_role = decoded.get('role', '')
            if user_role == 'FREE':
                config.is_paid_user = False
    except jwt.InvalidTokenError as e:
        error_type = "token_expired" if isinstance(e, jwt.ExpiredSignatureError) else f"invalid_token: {str(e)}"
        print(f"JWT error: {error_type}")
        error_time = time.time()
        error_message = "您的登入已過期，請重新整理頁面後再試。"
        payload = {
            "user_id": request.user_id,
            "started": round(error_time),
            "lang": request.lang,
            "question_type": "",
            "question": request.message,
            "answer": error_message,
            "prompt_token_count": 0,
            "candidates_token_count": 0,
            "cached_content_token_count": 0,
            "thoughts_token_count": 0,
            "tool_use_prompt_token_count": 0,
            "total_token_count": 0,
            "cost": 0,
            "models_used": "",
            "extras_json": json.dumps({"error": error_type}),
            "requested": round(error_time),
            "responded": round(error_time),
            "state": "error"
        }
        requests.post(LOGGER, json=payload)
        return ChatResponse(
            response_html=error_message,
            response_markdown=error_message,
            cost=0,
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "thinking_tokens": 0, "total_tokens": 0},
            conversation_history=[],
            response_seconds=0,
            started=round(error_time),
            requested=round(error_time),
            responded=round(error_time)
        )

    request_time = time.time()
    token_counter = TokenCounter()
    
    # Track session start time per user
    global user_sessions, user_conversation_histories
    if request.user_id not in user_sessions:
        user_sessions[request.user_id] = request_time
    session_start_time = user_sessions[request.user_id]
    
    # Initialize conversation history for new users
    if request.user_id not in user_conversation_histories:
        user_conversation_histories[request.user_id] = []
    
    try:
        # Use stored conversation history if available, otherwise use request history
        conversation_history = user_conversation_histories[request.user_id] if user_conversation_histories[request.user_id] else request.conversation_history
        
        # Convert conversation history to Gemini format
        contents = []
        for msg in conversation_history:
            contents.append(types.Content(
                role="user" if msg.role == "user" else "model",
                parts=[types.Part.from_text(text=msg.content)]
            ))
        
        # Add current message
        user_prompt = request.message
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)]))
        
        # Check if this is a chart instruction first
        recent = contents[-2:]
        if len(recent) == 2 and recent[0].role == "user":
            recent = recent[-1:]
        user_prompt_type = get_user_prompt_type(recent, token_counter)

        # Check usage limits (MCP has no limits)
        if request.user_id != MCP_USER_ID:
            role_category = get_role_category(user_role)
            exceeded = await check_usage_limits(request.user_id, user_prompt_type, role_category)
            if exceeded:
                return JSONResponse(status_code=429, content=exceeded)

        # Initialize variables that will be used in logging
        user_language_code = None
        web_search_queries = []
        retrieval_ids = {}

        # Build system prompt using contents[-2:]
        system_prompt, user_language_code, web_search_queries, retrieval_ids = await build_system_prompt(user_prompt_type, contents[-2:], config, knowledge, token_counter, request.lang)

        # Add current page text to system prompt if provided
        if request.current_page_html:
            # Extract main tag content to exclude header and footer
            main_match = re.search(r'<main[^>]*>(.*?)</main>', request.current_page_html, re.DOTALL | re.IGNORECASE)
            html_content = main_match.group(1) if main_match else request.current_page_html
            system_prompt += '\n- 用戶當前頁面內容：'
            system_prompt += f'\n```\n{markdownify(html_content)}\n```\n'

        global last_system_prompt
        last_system_prompt = system_prompt

        # Generate response
        response_type = 'text/plain'
        response_schema = None
        tools = None#[types.Tool(function_declarations=function_declarations)]
        # print('config.thinking_budget', config.thinking_budget)
        response_text = generate_content(contents, system_prompt, response_type, response_schema, tools, token_counter, model=config.quality_model, thinking_config=types.ThinkingConfig(thinking_budget=config.thinking_budget)).text
        contents.append(types.Content(role="model", parts=[types.Part.from_text(text=response_text)]))
        # Keep only previous N rounds of conversation history
        contents = contents[-2 * config.conversation_rounds:]

        # Convert Gemini contents back to ChatMessage format and update conversation history
        updated_conversation_history = []
        for content in contents:
            updated_conversation_history.append(ChatMessage(
                role=content.role,
                content=content.parts[0].text
            ))
        
        # Store the updated conversation history for this user session
        user_conversation_histories[request.user_id] = updated_conversation_history
        
        print()
        pprint(updated_conversation_history)
        print()

        # Log chat to GitHub Gist
        if GITHUB_GIST_API and GITHUB_ACCESS_TOKEN:
            try:
                headers = {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
                    "X-GitHub-Api-Version": "2022-11-28"
                }
                r = requests.get(GITHUB_GIST_API, headers=headers)
                if r.status_code == 200:
                    chat_log = heading = '# MM AI 對話紀錄（由新到舊）\n---\n'
                    chat_log += user_prompt + '\n---\n' + response_text + '\n\n---\n'
                    chat_log += r.json()['files']['madam-log.md']['content'].strip(heading)
                    chat_log = chat_log[:700000]  # Truncate to first 700000 characters to avoid exceeding gist size limit
                    payload = {'files': {'madam-log.md': {"content": chat_log}}}
                    requests.patch(GITHUB_GIST_API, headers=headers, json=payload)
            except Exception as e:
                print(f"Warning: Could not log to GitHub Gist: {e}")
        
        response_time = time.time()
        response_seconds = response_time - request_time

        # Logger
        payload = {
            "user_id": request.user_id,
            "started": round(session_start_time),
            "lang": request.lang,
            "question_type": user_prompt_type,
            "question": user_prompt,
            "answer": response_text,
            "prompt_token_count": token_counter.prompt_token_count,
            "candidates_token_count": token_counter.candidates_token_count,
            "cached_content_token_count": token_counter.cached_content_token_count,
            "thoughts_token_count": token_counter.thoughts_token_count,
            "tool_use_prompt_token_count": token_counter.tool_use_prompt_token_count,
            "total_token_count": token_counter.total_token_count,
            "cost": token_counter.total_cost(),
            "models_used": config.quality_model,
            "extras_json": json.dumps({
                "語言": user_language_code,
                "分類": user_prompt_type,
                "檢索": retrieval_ids,
                "搜尋": web_search_queries,
                "位於": request.current_page_url
            }, ensure_ascii=False, indent=2),
            "requested": round(request_time),
            "responded": round(response_time),
            "state": "ok"
        }
        requests.post(LOGGER, json=payload)

        response_html = convert_to_html(response_text)

        return ChatResponse(
            response_html=response_html if request.response_type == 'html' else '',
            response_markdown=response_text,
            cost=token_counter.total_cost(),
            token_usage={
                "prompt_tokens": token_counter.prompt_token_count,
                "completion_tokens": token_counter.candidates_token_count,
                "thinking_tokens": token_counter.thoughts_token_count,
                "total_tokens": token_counter.total_token_count
            },
            conversation_history=updated_conversation_history,
            response_seconds=response_seconds,
            started=round(session_start_time),
            requested=round(request_time),
            responded=round(response_time)
        )
        
    except Exception as e:
        print(f"Chat error: {str(e)}")
        traceback.print_exc()  # Print full stack trace
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat-stream")
async def chat_stream(request: ChatRequest, request_obj: Request):
    """Streaming chat endpoint using Server-Sent Events"""
    # JWT validation (same logic as /chat)
    try:
        config = ConfigModel(**request.config) if request.config else ConfigModel()
        user_role = ''
        authorization = request_obj.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        elif request.jwt:
            token = request.jwt
        else:
            raise jwt.InvalidTokenError("JWT token required")
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience="macromicro.me")
        print(f"JWT decoded successfully: {decoded}")
        request.user_id = int(decoded.get('sub'))
        user_role = decoded.get('role', '')
        if user_role == 'FREE':
            config.is_paid_user = False
    except jwt.InvalidTokenError as e:
        error_type = "token_expired" if isinstance(e, jwt.ExpiredSignatureError) else f"invalid_token: {str(e)}"
        print(f"JWT error: {error_type}")
        return JSONResponse(status_code=401, content={"message": "您的登入已過期，請重新整理頁面後再試。"})

    request_time = time.time()
    token_counter = TokenCounter()

    global user_sessions, user_conversation_histories
    if request.user_id not in user_sessions:
        user_sessions[request.user_id] = request_time
    session_start_time = user_sessions[request.user_id]

    if request.user_id not in user_conversation_histories:
        user_conversation_histories[request.user_id] = []

    # Pre-build contents for usage check before starting the stream
    conversation_history = user_conversation_histories[request.user_id] if user_conversation_histories[request.user_id] else request.conversation_history
    contents = []
    for msg in conversation_history:
        contents.append(types.Content(
            role="user" if msg.role == "user" else "model",
            parts=[types.Part.from_text(text=msg.content)]
        ))
    user_prompt = request.message
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)]))

    recent = contents[-2:]
    if len(recent) == 2 and recent[0].role == "user":
        recent = recent[-1:]
    user_prompt_type = get_user_prompt_type(recent, token_counter)

    # Check usage limits before starting the stream
    role_category = get_role_category(user_role)
    exceeded = await check_usage_limits(request.user_id, user_prompt_type, role_category)
    if exceeded:
        return JSONResponse(status_code=429, content=exceeded)

    async def event_stream():
        nonlocal contents
        try:
            user_language_code = None
            web_search_queries = []
            retrieval_ids = {}

            system_prompt, user_language_code, web_search_queries, retrieval_ids = await build_system_prompt(user_prompt_type, contents[-2:], config, knowledge, token_counter, request.lang)

            if request.current_page_html:
                main_match = re.search(r'<main[^>]*>(.*?)</main>', request.current_page_html, re.DOTALL | re.IGNORECASE)
                html_content = main_match.group(1) if main_match else request.current_page_html
                system_prompt += '\n- 用戶當前頁面內容：'
                system_prompt += f'\n```\n{markdownify(html_content)}\n```\n'

            global last_system_prompt
            last_system_prompt = system_prompt

            # Stream Gemini response
            response_text = ""
            async for chunk_text in generate_content_stream(contents, system_prompt, token_counter, model=config.quality_model, thinking_config=types.ThinkingConfig(thinking_budget=config.thinking_budget)):
                response_text += chunk_text
                yield f'event: chunk\ndata: {json.dumps({"text": chunk_text})}\n\n'

            # Update conversation history
            contents.append(types.Content(role="model", parts=[types.Part.from_text(text=response_text)]))
            contents = contents[-2 * config.conversation_rounds:]

            updated_conversation_history = []
            for content in contents:
                updated_conversation_history.append(ChatMessage(
                    role=content.role,
                    content=content.parts[0].text
                ))
            user_conversation_histories[request.user_id] = updated_conversation_history

            # Log chat to GitHub Gist
            if GITHUB_GIST_API and GITHUB_ACCESS_TOKEN:
                try:
                    headers = {
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
                        "X-GitHub-Api-Version": "2022-11-28"
                    }
                    r = requests.get(GITHUB_GIST_API, headers=headers)
                    if r.status_code == 200:
                        chat_log = heading = '# MM AI 對話紀錄（由新到舊）\n---\n'
                        chat_log += user_prompt + '\n---\n' + response_text + '\n\n---\n'
                        chat_log += r.json()['files']['madam-log.md']['content'].strip(heading)
                        chat_log = chat_log[:700000]
                        payload = {'files': {'madam-log.md': {"content": chat_log}}}
                        requests.patch(GITHUB_GIST_API, headers=headers, json=payload)
                except Exception as e:
                    print(f"Warning: Could not log to GitHub Gist: {e}")

            response_time = time.time()
            response_seconds = response_time - request_time

            # Logger
            payload = {
                "user_id": request.user_id,
                "started": round(session_start_time),
                "lang": request.lang,
                "question_type": user_prompt_type,
                "question": user_prompt,
                "answer": response_text,
                "prompt_token_count": token_counter.prompt_token_count,
                "candidates_token_count": token_counter.candidates_token_count,
                "cached_content_token_count": token_counter.cached_content_token_count,
                "thoughts_token_count": token_counter.thoughts_token_count,
                "tool_use_prompt_token_count": token_counter.tool_use_prompt_token_count,
                "total_token_count": token_counter.total_token_count,
                "cost": token_counter.total_cost(),
                "models_used": config.quality_model,
                "extras_json": json.dumps({
                    "語言": user_language_code,
                    "分類": user_prompt_type,
                    "檢索": retrieval_ids,
                    "搜尋": web_search_queries,
                    "位於": request.current_page_url
                }, ensure_ascii=False, indent=2),
                "requested": round(request_time),
                "responded": round(response_time),
                "state": "ok"
            }
            requests.post(LOGGER, json=payload)

            # Send done event with final data
            done_data = {
                "response_markdown": response_text,
                "token_usage": {
                    "prompt_tokens": token_counter.prompt_token_count,
                    "completion_tokens": token_counter.candidates_token_count,
                    "thinking_tokens": token_counter.thoughts_token_count,
                    "total_tokens": token_counter.total_token_count
                },
                "cost": token_counter.total_cost(),
                "response_seconds": round(response_seconds, 2)
            }
            yield f'event: done\ndata: {json.dumps(done_data)}\n\n'

        except Exception as e:
            print(f"Chat stream error: {str(e)}")
            traceback.print_exc()
            yield f'event: error\ndata: {json.dumps({"message": str(e)})}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, request_obj: Request):
    """Search endpoint for chat widget search mode"""
    try:
        authorization = request_obj.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        elif request.jwt:
            token = request.jwt
        else:
            raise jwt.InvalidTokenError("JWT token required")
        jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience="macromicro.me")
    except jwt.InvalidTokenError as e:
        error_type = "token_expired" if isinstance(e, jwt.ExpiredSignatureError) else f"invalid_token: {str(e)}"
        print(f"JWT error in /search: {error_type}")
        return JSONResponse(status_code=401, content={"message": "您的登入已過期，請重新整理頁面後再試。"})

    try:
        print(f"Received search request: {request.query}")
        results = google_search_site(request.query, request.lang)
        # Convert markdown to HTML for search results too
        results_html = md.convert(results)
        # Make links open in new tab
        results_html = results_html.replace('<a href=', '<a target="_blank" rel="noopener noreferrer" href=')
        return SearchResponse(results=results_html)
    except Exception as e:
        print(f"Search error: {str(e)}")
        traceback.print_exc()  # Print full stack trace
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/system-prompt", response_model=SystemPromptResponse)
async def get_system_prompt(request: SystemPromptRequest):
    """Get the last system prompt used in content generation"""
    try:
        print(f"Received system prompt request")
        global last_system_prompt
        return SystemPromptResponse(system_prompt=last_system_prompt)
    except Exception as e:
        print(f"System prompt error: {str(e)}")
        traceback.print_exc()  # Print full stack trace
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def serve_index():
    """Serve the main index.html page"""
    if os.getenv("ENABLE_FRONTEND", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse("test-frontend/index.html")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/config")
async def get_frontend_config():
    """Get frontend configuration from environment variables"""
    if os.getenv("ENABLE_FRONTEND", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "MM_HIDE_CHAT_BUBBLE": os.getenv("MM_HIDE_CHAT_BUBBLE", "false")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)