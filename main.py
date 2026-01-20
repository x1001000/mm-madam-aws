from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
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
REMOTE_MCP_SERVER = os.getenv('REMOTE_MCP_SERVER')
GITHUB_GIST_API = os.getenv('GITHUB_GIST_API')
GITHUB_ACCESS_TOKEN = os.getenv('GITHUB_ACCESS_TOKEN')
LOGGER = os.getenv('LOGGER')
JWT_SECRET = os.getenv('JWT_SECRET')

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
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="."), name="static")

# automatically set to 20 days ago
AFTER_DATE = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
# manually update
PRICING = {
    'gemini-2.5-flash-lite': {'input': 0.1, 'output': 0.4, 'thinking': 0.4, 'caching': 0.01},
    'gemini-2.5-flash': {'input': 0.3, 'output': 2.5, 'thinking': 2.5, 'caching': 0.03},
    'gemini-3-flash-preview': {'input': 0.5, 'output': 3, 'thinking': 3, 'caching': 0.05},
    'gemini-2.5-pro': {'input': 1.25, 'output': 10, 'thinking': 10, 'caching': 0.125},
    'gemini-3-pro-preview': {'input': 2, 'output': 12, 'thinking': 12, 'caching': 0.2},
}
DEFAULT_MODEL = 'gemini-3-flash-preview'

# SITE_LANGUAGES = ['繁體中文', '简体中文', 'English']
SUBDOMAINS = ['www', 'sc', 'en']
LANG_ROUTES = ['zh-tw', 'zh-cn', 'en-001']
LANG_IDS = {
    'zh-hant': 0, 'zh-tw': 0, 'tw': 0, 'zh': 0,
    'zh-hans': 1, 'zh-cn': 1, 'cn': 1,
}

# Request/Response models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    user_id: int
    message: str
    jwt: Optional[str] = None  # optional for mm-mcp (user_id 101001000)
    conversation_history: Optional[List[ChatMessage]] = []
    config: Optional[Dict[str, Any]] = {}
    sub_level: Optional[str] = None
    response_type: Optional[str] = 'html'
    current_page_html: Optional[str] = None  # text content of the page where chat bubble is used
    current_page_url: Optional[str] = None  # URL of the page where chat bubble is used (for logging)

class ChatResponse(BaseModel):
    response: str
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

@lru_cache(maxsize=1)
def get_base_system_prompt():
    """Fetch and cache the base system prompt (only downloaded once per app lifecycle)"""
    text = requests.get(SYSTEM_PROMPT_URL).text
    parts = text.split('\n\n')[:3]
    return parts[0], parts[1], parts[2]  # system_prompt, for_paid_user, for_free_user

@lru_cache(maxsize=1)
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

        # Local CSV files
        local_csv_files = glob.glob('knowledge/*/*/_log.csv') # TBD: remote CSV files from KNOWLEDGE_CSV_API
        local_csv_files.append('/tmp/podcast.csv')
        
        # Remote CSV files
        remote_csv_files = [
            f'{KNOWLEDGE_CSV_API}/chart_tc.csv',
            f'{KNOWLEDGE_CSV_API}/quickie.csv',
            f'{KNOWLEDGE_CSV_API}/post.csv',
            f'{KNOWLEDGE_CSV_API}/post_en.csv',
            f'{KNOWLEDGE_CSV_API}/edm.csv',
        ]

        # Fetch all remote CSVs concurrently
        async def fetch_remote_csvs(urls):
            async with httpx.AsyncClient() as client:
                tasks = [client.get(url) for url in urls]
                return await asyncio.gather(*tasks)

        responses = asyncio.run(fetch_remote_csvs(remote_csv_files))
        remote_csv_data = {url: r.text for url, r in zip(remote_csv_files, responses)}

        csv_files = local_csv_files + remote_csv_files

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
    except Exception as e:
        print(f"Error loading knowledge: {e}")
        
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

def get_user_prompt_type(contents, token_counter):
    system_prompt = '用戶訊息分類：總經財經市場新聞時事相關問題、網站功能操作客服或其他問題、製圖請求，以「總經」、「客服」、「製圖」三選一回傳'
    response_type = 'application/json'
    response_schema = str
    tools = None
    try:
        response_parsed = generate_content(contents, system_prompt, response_type, response_schema, tools, token_counter).parsed
        print(response_parsed)
        return response_parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Type detection error: {e}")

def get_user_language_code(user_prompt, token_counter):
    system_prompt = 'Given a user query, identify its language code'
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
    system_prompt = 'Given a user query, identify its language code'
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


def google_search_site(query):
    results = []
    try:
        r = requests.get(f"https://www.googleapis.com/customsearch/v1?key={SEARCH_API_KEY}&cx=414d6323cec6d419d&q={query}")
        d = r.json()
        items = d.get('items', [])
        for item in items:
            print(item["title"])
            print(item["link"])
            # Skip items with '用戶圖' or 'UGC' in title
            if '用戶圖' in item["title"] or 'UGC' in item["title"].upper():
                continue
            if '/series' in item["link"]:
                results.append(f'📈 [{item["title"]}]({item["link"]})')
            if '/charts' in item["link"]:
                results.append(f'📊 [{item["title"]}]({item["link"]})')
            if '/blog' in item["link"]:
                results.append(f'📝 [{item["title"]}]({item["link"]})')
        results = sorted(results[:6]) # first 6 results sorted in 📈 📊 📝 order
        results.append(f'🔍 [全站搜尋](/search?q={query})')
        return '\n\n'.join(results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google site search error: {e}")

async def get_chart_config_from_mcp(user_prompt):
    return '此功能暫未開放，敬請期待！'


async def build_system_prompt(user_prompt_type, contents, config, knowledge, token_counter):
    """Build the system prompt based on user input and configuration (async version with parallel API calls)"""
    # Initialize tracking variables
    web_search_queries = []
    retrieval_ids = {}
    
    user_prompt = contents[-1]
    N_most_relevant = config.N_most_relevant
    no_single_series = config.no_single_series

    # Get base system prompt (cached)
    system_prompt, for_paid_user, for_free_user = get_base_system_prompt()

    # For non-financial queries, use the original sequential approach
    if '客服' in user_prompt_type:
        # Detect language (single API call, no need for parallelization)
        user_language_code = get_user_language_code(user_prompt, token_counter)
        lang_id = LANG_IDS.get(user_language_code.lower(), 2)
        SUBDOMAIN = SUBDOMAINS[lang_id]

        system_prompt += f'\n- SUBDOMAIN = "{SUBDOMAIN}"'
        system_prompt += f'\n- You MUST respond in user language code: "{user_language_code}"'

        if config.has_help_center:
            lang_route = LANG_ROUTES[lang_id]
            system_prompt += f'\n- MM幫助中心網址 https://support.macromicro.me/hc/{lang_route}'
            system_prompt += '\n- 切勿提供來信或來電的客服聯繫方式'
            retrieval, ids = get_retrieval_from_help_center(f'hc/{lang_route}/_log.csv', user_prompt, knowledge, token_counter, N_most_relevant)
            if retrieval:
                retrieval_ids['help_center'] = ids
                system_prompt += '\n- MM幫助中心的相關資料'
                system_prompt += f'（hyperlink pattern: https://support.macromicro.me/hc/{lang_route}/articles/{{id}}）'
                system_prompt += f'\n```\n{retrieval}\n```\n'
        system_prompt += '\n- 若非網站功能操作客服相關問題，你會婉拒回答'
        system_prompt += '\n\n---\n' + requests.get(MARKETING_PROMPT_URL).text

        return system_prompt, SUBDOMAIN, user_language_code, web_search_queries, retrieval_ids

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
    lang_id = LANG_IDS.get(user_language_code.lower(), 2)
    SUBDOMAIN = SUBDOMAINS[lang_id]

    system_prompt += f'\n- SUBDOMAIN = "{SUBDOMAIN}"'
    system_prompt += f'\n- You MUST respond in user language code: "{user_language_code}"'

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
                system_prompt += '，可引用，但切勿超連結'
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
                system_prompt += '，可引用，但切勿超連結'
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
            system_prompt += '，可引用，但切勿超連結'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    # Process podcast retrieval
    if 'podcast' in results_dict and not isinstance(results_dict['podcast'], Exception):
        retrieval, ids = results_dict['podcast']
        if retrieval:
            retrieval_ids['podcast'] = ids
            system_prompt += '\n- MM Podcast的相關資料'
            system_prompt += '，可引用，但切勿超連結'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    # Process google search retrieval
    if 'google_search' in results_dict and not isinstance(results_dict['google_search'], Exception):
        result = results_dict['google_search']
        if result[0]:  # Check if retrieval text exists
            retrieval, queries = result
            web_search_queries.extend(queries)
            system_prompt += '\n- 網路搜尋的相關資料'
            system_prompt += f'\n```\n{retrieval}\n```\n'

    return system_prompt, SUBDOMAIN, user_language_code, web_search_queries, retrieval_ids

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint"""
    # Verify JWT
    try:
        config = ConfigModel(**request.config) if request.config else ConfigModel()
        # if not mm-mcp-aws/server.py user_id 101001000
        if request.user_id != 101001000:
            if not request.jwt:
                raise jwt.InvalidTokenError("JWT token required")
            decoded = jwt.decode(request.jwt, JWT_SECRET, algorithms=["HS256"], audience="macromicro.me")
            print(f"JWT decoded successfully: {decoded}")
            # if not mm-madam-aws/chat-widget.js jwt user_id '1001000' (Subject must be a string)
            if decoded.get('sub') != '1001000' and decoded.get('role') != 'BIZ':
                config.is_paid_user = False
    except jwt.InvalidTokenError as e:
        error_type = "token_expired" if isinstance(e, jwt.ExpiredSignatureError) else f"invalid_token: {str(e)}"
        print(f"JWT error: {error_type}")
        error_time = time.time()
        error_message = "您的登入已過期，請重新整理頁面後再試。"
        payload = {
            "started": round(error_time),
            "user_id": request.user_id,
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
            response=error_message,
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
        user_prompt_type = get_user_prompt_type(contents[-2:], token_counter)

        # Initialize variables that will be used in logging
        user_language_code = None
        web_search_queries = []
        retrieval_ids = {}

        if '製圖' in user_prompt_type:
            # Chart instruction - get chart config from MCP and return directly
            chart_config = await get_chart_config_from_mcp(user_prompt)
            if chart_config:
                response_text = chart_config
            else:
                response_text = "無法生成圖表配置，請提供更具體的圖表需求"
            SUBDOMAIN = SUBDOMAINS[0]  # Default subdomain
            user_language_code = "zh-TW"  # Default language code for chart instructions
        else:
            # Build system prompt using contents[-2:]
            system_prompt, SUBDOMAIN, user_language_code, web_search_queries, retrieval_ids = await build_system_prompt(user_prompt_type, contents[-2:], config, knowledge, token_counter)

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

        # hard fix hallucination
        if SUBDOMAIN == 'en':
            response_text = re.sub(r'https://(www|sc)\.macromicro', f'https://en.macromicro', response_text)

        # Insert preview images under chart hyperlink items
        # Pattern matches: * [Title](url) or 1. [Title](url) or * Prefix：[Title](url) (bulleted or numbered list items)
        # Allows optional text (like MM圖表：) before the markdown link
        chart_hyperlink_pattern = r'(?:\*|\d+\.)\s+[^\[]*\[(.+?)\]\((https?://(?:[^/]+\.)?macromicro\.me/charts/[^\s)]+)\)(?:\n|$)'

        def insert_preview(match):
            title = match.group(1)
            chart_url = match.group(2)
            chart_id = chart_url.split('/charts/')[-1].split('/')[0]
            preview_url = f'https://cdn.macromicro.me/files/charts/{chart_id[-3:].zfill(3)}/{chart_id}-{SUBDOMAIN}.png'.replace('www', 'tc')
            return f'\n* [{title}]({chart_url})\n[![]({preview_url})]({chart_url})\n'

        response_text = re.sub(chart_hyperlink_pattern, insert_preview, response_text)

        # Fix markdown rendering bug: add extra newline between bold text and list items
        # Pattern matches: **bold text** followed by newline and list marker (* or - or 1.)
        response_text = re.sub(r'(\*\*.+?\*\*)\n([\*\-]|\d+\.)', r'\1\n\n\2', response_text)

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
            "started": round(session_start_time),
            "user_id": request.user_id,
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
        
        # Convert markdown to HTML
        response_html = md.convert(response_text)
        # Make images responsive (fit width)
        response_html = response_html.replace('<img ', '<img style="max-width: 100%; height: auto;" ')
        # Make links open in new tab
        response_html = response_html.replace('<a href=', '<a target="_blank" rel="noopener noreferrer" href=')
        
        return ChatResponse(
            response=response_html if request.response_type == 'html' else response_text,
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

@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """Search endpoint for chat widget search mode"""
    try:
        print(f"Received search request: {request.query}")
        results = google_search_site(request.query)
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
    return FileResponse("index.html")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.get("/config")
async def get_frontend_config():
    """Get frontend configuration from environment variables"""
    return {
        "MM_HIDE_CHAT_BUBBLE": os.getenv("MM_HIDE_CHAT_BUBBLE", "false")
    }

from mangum import Mangum
handler = Mangum(app, lifespan="off")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)