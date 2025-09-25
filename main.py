from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from google import genai
from google.genai import types
import csv
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
import markdown
# Enable the tables extension
md = markdown.Markdown(extensions=['tables', 'nl2br'])
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
SEARCH_API_KEY = os.getenv('SEARCH_API_KEY')
SYSTEM_PROMPT_URL = os.getenv('SYSTEM_PROMPT_URL')
KNOWLEDGE_CSV_API = os.getenv('KNOWLEDGE_CSV_API')
CHARTS_DATA_API = os.getenv('CHARTS_DATA_API')
REMOTE_MCP_SERVER = os.getenv('REMOTE_MCP_SERVER')
GITHUB_GIST_API = os.getenv('GITHUB_GIST_API')
GITHUB_ACCESS_TOKEN = os.getenv('GITHUB_ACCESS_TOKEN')
LOGGER_DEV = os.getenv('LOGGER_DEV')
LOGGER = os.getenv('LOGGER')

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
    # 'gemini-2.5-flash-lite-preview-06-17': {'input': 0.1, 'output': 0.4, 'thinking': 0.4, 'caching': 0.025}, TOO SMALL
    'gemini-2.5-flash': {'input': 0.3, 'output': 2.5, 'thinking': 2.5, 'caching': 0.075},
    'gemini-2.5-pro': {'input': 1.25, 'output': 10, 'thinking': 10, 'caching': 0.31},
}
DEFAULT_MODEL = 'gemini-2.5-flash'

# SITE_LANGUAGES = ['繁體中文', '简体中文', 'English']
SUBDOMAINS = ['www', 'sc', 'en']
LANG_ROUTES = ['zh-tw', 'zh-cn', 'en-001']
LANG_IDS = {
    'zh-tw': 0, 'tw': 0, 'zh': 0,
    'zh-cn': 1, 'cn': 1,
}

# Request/Response models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    user_id: int
    message: str
    conversation_history: Optional[List[ChatMessage]] = []
    config: Optional[Dict[str, Any]] = {}
    sub_level: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
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
    has_hc: bool = True
    has_google_search: bool = True
    conversation_rounds: int = 2
    thinking_budget: int = 500
    quality_model: str = 'gemini-2.5-flash'

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

# Initialize client
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")
client = genai.Client(api_key=GEMINI_API_KEY)

@lru_cache(maxsize=1)
def get_knowledge():
    knowledge = {}
    try:
        # Local CSV files
        local_csv_files = [
            'knowledge/chart_tc.csv',
        ] + glob.glob('knowledge/hc/*/_log.csv')
        
        # Remote CSV files (only if API URL is available)
        remote_csv_files = []
        if KNOWLEDGE_CSV_API:
            remote_csv_files = [
                f'{KNOWLEDGE_CSV_API}/quickie.csv',
                f'{KNOWLEDGE_CSV_API}/post.csv',
                f'{KNOWLEDGE_CSV_API}/post_en.csv',
                f'{KNOWLEDGE_CSV_API}/edm.csv',
            ]
        
        csv_files = local_csv_files + remote_csv_files
        
        for csv_file in csv_files:
            try:
                # Read CSV data using native csv module
                if csv_file.startswith('http'):
                    r = requests.get(csv_file)
                    lines = r.text.splitlines()
                    reader = csv.DictReader(lines)
                    data = list(reader)
                else:
                    with open(csv_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        data = list(reader)
                
                # Filter by date if date column exists
                if data and 'date' in data[0]:
                    data = [row for row in data if row['date'] > AFTER_DATE]
                
                csv_file_key = csv_file.split('knowledge/')[-1].split('csv/')[-1]
                knowledge[csv_file_key] = data
                
                # Create first 2 columns JSON equivalent
                if data:
                    first_cols = list(data[0].keys())[:2]
                    first_two_cols = [{col: row[col] for col in first_cols if col in row} for row in data]
                    knowledge[csv_file_key + ' => df.iloc[:,:2].to_json'] = json.dumps(first_two_cols, ensure_ascii=False)
            except Exception as e:
                print(f"Warning: Could not load {csv_file}: {e}")
                continue
                
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
    # pprint(response.usage_metadata)
    token_counter.accumulate(response.usage_metadata, model)
    return response

def get_user_language_code(user_prompt, token_counter):
    system_prompt = 'Given a user query, identify its language code'
    response_type = 'application/json'
    response_schema = str
    tools = None
    try:
        return generate_content(user_prompt, system_prompt, response_type, response_schema, tools, token_counter).parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Language detection error: {e}")

def get_user_prompt_type(contents, token_counter):
    system_prompt = 'Classify user prompt：總經財經時事類、網站客服或其他類、製圖指令類'
    response_type = 'application/json'
    response_schema = str
    tools = None
    try:
        response_parsed = generate_content(contents, system_prompt, response_type, response_schema, tools, token_counter).parsed
        print(response_parsed)
        return response_parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Type detection error: {e}")

def get_most_relevant_ids(csv_df_json, user_prompt, knowledge, token_counter):
    system_prompt = 'Given a user query, identify up to 5 of the most relevant IDs in the JSON below.\n'
    system_prompt += knowledge[csv_df_json]
    response_type = 'application/json'
    response_schema = list[int]
    tools = None
    try:
        response_parsed = generate_content(user_prompt, system_prompt, response_type, response_schema, tools, token_counter).parsed
        return response_parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ID retrieval error: {e}")

def get_retrieval_from_charts_data_api(csv_file, user_prompt, knowledge, token_counter):
    if ids := get_most_relevant_ids(csv_file + ' => df.iloc[:,:2].to_json', user_prompt, knowledge, token_counter):
        data = []
        for _id in ids:
            r = requests.get(f'{CHARTS_DATA_API}/{_id}')
            d = r.json()
            d['data'][f'c:{_id}']['id'] = d['data'][f'c:{_id}']['info']['id']
            d['data'][f'c:{_id}']['slug'] = d['data'][f'c:{_id}']['info']['slug']
            d['data'][f'c:{_id}']['name_tc'] = d['data'][f'c:{_id}']['info']['name_tc']
            d['data'][f'c:{_id}']['description_tc'] = d['data'][f'c:{_id}']['info']['description_tc']
            series_names = [series_config['name_tc'] for series_config in d['data'][f'c:{_id}']['info']['chart_config']['seriesConfigs']]
            series = d['data'][f'c:{_id}']['series']
            for i in range(len(series)):
                series[i] = series[i][-2:]
            d['data'][f'c:{_id}']['series'] = dict(zip(series_names, series))
            del d['data'][f'c:{_id}']['info']
            data.append(d['data'][f'c:{_id}'])
        return json.dumps(data, ensure_ascii=False)

def get_retrieval(csv_file, user_prompt, knowledge, token_counter):
    if ids := get_most_relevant_ids(csv_file + ' => df.iloc[:,:2].to_json', user_prompt, knowledge, token_counter):
        data = knowledge[csv_file]
        # Filter data by matching ids
        filtered_data = [row for row in data if int(row.get('id', 0)) in ids]
        return json.dumps(filtered_data, ensure_ascii=False)

def get_retrieval_from_google_search(user_prompt, token_counter):
    system_prompt = None
    response_type = 'text/plain'
    response_schema = None
    tools = [types.Tool(google_search=types.GoogleSearch())]
    try:
        response_text = generate_content(user_prompt, system_prompt, response_type, response_schema, tools, token_counter).text
        return response_text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google search error: {e}")

server_params = StdioServerParameters(
    command="npx", 
    args=[
        "mcp-remote",
        REMOTE_MCP_SERVER,
        "--transport",
        "http-only"
    ]
)
async def get_chart_config_from_mcp(user_prompt):
    try:
        # Connect to MCP server
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the session
                await session.initialize()
                
                response = await client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=user_prompt,
                    config=genai.types.GenerateContentConfig(
                        temperature=0,
                        tools=[session],  # uses the session, will automatically call the tool
                        # Uncomment if you **don't** want the SDK to automatically call the tool
                        # automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(
                        #     disable=True
                        # ),
                    ),
                )
                # chart_json = response.automatic_function_calling_history[2].parts[0].function_response.response.result.content[0].text
                # pprint(response.model_dump())
                function_response = response.model_dump()['automatic_function_calling_history'][-1]['parts'][0]['function_response']['response']
                if function_response.get('result'):
                    chart_json = function_response['result']['content'][0]['text']
                    chart_json = json.dumps(json.loads(chart_json), indent='　', ensure_ascii=False)
                    # print(chart_json)
                    return chart_json
    
    except Exception as e:
        print(f"MCP service error: {e}")
        return ""

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

def get_retrieval_from_help_center(csv_file, user_prompt, knowledge, token_counter):
    if ids := get_most_relevant_ids(csv_file + ' => df.iloc[:,:2].to_json', user_prompt, knowledge, token_counter):
        # Create list of dictionaries instead of DataFrame
        data = []
        for _id in ids:
            with open('knowledge/' + csv_file.replace('_log', str(_id)).replace('csv', 'html')) as f:
                html_content = ''.join(f.readlines())
            data.append({'id': _id, 'html': html_content})
        return json.dumps(data, ensure_ascii=False)

def build_system_prompt(user_prompt_type, contents, config, knowledge, token_counter):
    """Build the system prompt based on user input and configuration"""
    # Detect language
    user_prompt = contents[-1]
    user_language_code = get_user_language_code(user_prompt, token_counter)
    lang_id = LANG_IDS.get(user_language_code.lower(), 2)
    SUBDOMAIN = SUBDOMAINS[lang_id]
    
    # Determine prompt type (1: financial, 2: customer service, 3: chart instruction)
    # user_prompt_type = get_user_prompt_type(contents, token_counter)
    
    # Get base system prompt
    system_prompt = requests.get(SYSTEM_PROMPT_URL).text
    system_prompt += f'\n- SUBDOMAIN = "{SUBDOMAIN}"'
    system_prompt += f'\n- You MUST respond in user language code: "{user_language_code}"'
    # system_prompt += f'\n- You MUST NOT hyperlink to any edm(MM獨家報告){', quickie(MM短評), and Chinese blog(MM中文部落格)' if SUBDOMAIN == 'en' else ''}.\n'
    system_prompt += '\n\n---\n'

    if '總經' in user_prompt_type:
        if not config.is_paid_user:
            system_prompt += '\n- 你會鼓勵用戶升級成為付費用戶就能享有完整問答服務，並且提供訂閱方案連結：'
            system_prompt += f'https://{SUBDOMAIN}.macromicro.me/subscribe'
        
        # Add retrievals based on config
        if config.has_chart and config.is_paid_user:
            if retrieval := get_retrieval_from_charts_data_api('chart_tc.csv', user_prompt, knowledge, token_counter):
                system_prompt += '\n- MM圖表的相關資料，當中時間序列（series）包含前值及最新數據，務必引用，並將文字或數據超連結至：'
                system_prompt += f'https://{SUBDOMAIN}.macromicro.me/charts/{{id}}/{{slug}}'
                system_prompt += f'\n```\n{retrieval}\n```\n'
        
        if config.has_quickie and config.is_paid_user:
            if retrieval := get_retrieval('quickie.csv', user_prompt, knowledge, token_counter):
                system_prompt += '\n- MM短評的相關資料'
                if SUBDOMAIN == 'en':
                    system_prompt += '，可引用，但切勿超連結'
                else:
                    system_prompt += f'（hyperlink pattern: https://{SUBDOMAIN}.macromicro.me/quickie?id={{id}}）'
                system_prompt += f'\n```\n{retrieval}\n```\n'
        
        if config.has_blog and config.is_paid_user:
            if retrieval := get_retrieval('post.csv', user_prompt, knowledge, token_counter):
                system_prompt += '\n- MM中文部落格的相關資料'
                if SUBDOMAIN == 'en':
                    system_prompt += '，可引用，但切勿超連結'
                else:
                    system_prompt += f'（hyperlink pattern: https://{SUBDOMAIN}.macromicro.me/blog/{{slug}}）'
                system_prompt += f'\n```\n{retrieval}\n```\n'
            if retrieval := get_retrieval('post_en.csv', user_prompt, knowledge, token_counter):
                system_prompt += '\n- MM英文部落格的相關資料'
                system_prompt += f'（hyperlink pattern: https://en.macromicro.me/blog/{{slug}}）'
                system_prompt += f'\n```\n{retrieval}\n```\n'
        
        if config.has_edm and config.is_paid_user:
            if retrieval := get_retrieval('edm.csv', user_prompt, knowledge, token_counter):
                system_prompt += '\n- MM獨家報告的相關資料'
                system_prompt += '，可引用，但切勿超連結'
                system_prompt += f'\n```\n{retrieval}\n```\n'
        
        if config.has_google_search:
            if retrieval := get_retrieval_from_google_search(user_prompt, token_counter):
                system_prompt += '\n- 網路搜尋的相關資料'
                system_prompt += f'\n```\n{retrieval}\n```\n'
    else:
        if config.has_hc:
            lang_route = LANG_ROUTES[lang_id]
            system_prompt += f'\n- MM幫助中心網址 https://support.macromicro.me/hc/{lang_route}'
            system_prompt += '\n- 切勿提供來信或來電的客服聯繫方式'
            if retrieval := get_retrieval_from_help_center(f'hc/{lang_route}/_log.csv', user_prompt, knowledge, token_counter):
                system_prompt += '\n- MM幫助中心的相關資料'
                system_prompt += f'（hyperlink pattern: https://support.macromicro.me/hc/{lang_route}/articles/{{id}}）'
                system_prompt += f'\n```\n{retrieval}\n```\n'
        system_prompt += '\n- 若非網站客服相關問題，你會婉拒回答'
    
    return system_prompt, SUBDOMAIN

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint"""
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
        # print()
        # print(request.message)
        # print(request.sub_level)
        # pprint(request.config)
        config = ConfigModel(**request.config) if request.config else ConfigModel()
        
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
        
        if '製圖' in user_prompt_type:
            # Chart instruction - get chart config from MCP and return directly
            chart_config = await get_chart_config_from_mcp(user_prompt)
            if chart_config:
                response_text = chart_config
            else:
                response_text = "無法生成圖表配置，請提供更具體的圖表需求"
            SUBDOMAIN = SUBDOMAINS[0]  # Default subdomain
        else:
            # Build system prompt using contents[-2:]
            system_prompt, SUBDOMAIN = build_system_prompt(user_prompt_type, contents[-2:], config, knowledge, token_counter)
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
        if SUBDOMAIN == 'en':   # hard fix hallucination
            response_text = re.sub(r'https://(www|sc)\.macromicro', f'https://en.macromicro', response_text)

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
            "requested": round(request_time),
            "responded": round(response_time),
            "state": "ok"
        }
        requests.post(LOGGER, json=payload)
        
        # Convert markdown to HTML
        response_html = md.convert(response_text)
        # Make links open in new tab
        response_html = response_html.replace('<a href=', '<a target="_blank" rel="noopener noreferrer" href=')
        
        return ChatResponse(
            response=response_html,
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