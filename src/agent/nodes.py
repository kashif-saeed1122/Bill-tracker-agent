from src.agent.state import AgentState
from src.agent.tools import (
    classify_intent,
    scan_emails,
    parse_pdf,
    extract_data,
    save_bill,
    add_to_rag,
    rag_search,
    query_database,
    web_search,
    create_reminder
)
from datetime import datetime, timedelta
import os
from src.config.settings import settings
from src.modules.llm_interface import LLMInterface



def intent_classifier_node(state: AgentState) -> AgentState:
    print(f"\n🎯 INTENT CLASSIFIER: Analyzing query...")
    if "intent_classification" in state.get("completed_steps", []):
        return state
    
    result = classify_intent.invoke({"user_query": state["user_query"]})
    
    if result.get("success"):
        state["intent"] = result.get("intent", "unknown")
        state["intent_confidence"] = result.get("confidence", 0.0)
        state["entities"] = result.get("entities", {})
        
        scan_type = state["entities"].get("email_scan_type", "bills")
        if state["intent"] == "scan_emails" and scan_type == "bills":
             state["intent"] = "scan_bills"
             
        state["completed_steps"] = state.get("completed_steps", []) + ["intent_classification"]
        print(f"   Intent: {state['intent']} (Type: {scan_type})")
    else:
        state["errors"] = state.get("errors", []) + [f"Intent failed: {result.get('error')}"]
        state["intent"] = "unknown"
    return state


def planner_node(state: AgentState) -> AgentState:
    print(f"\n📋 PLANNER: Creating execution plan...")
    intent = state["intent"]
    
    plan = []
    
    if intent in ["scan_bills", "scan_emails"]:
        plan = ["email_scanner"]
        plan.extend(["pdf_processor", "data_extractor", "database_saver"])
            
    elif intent == "query_history" or intent == "analyze_spending":
        plan = ["database_query", "response_generator"]
        
    elif intent == "set_reminder":
        plan = ["database_query", "reminder_creator", "response_generator"]
        
    elif intent == "find_alternatives":
        plan = ["database_query", "web_searcher", "response_generator"]
        
    elif intent == "manual_add":
        plan = ["data_extractor", "database_saver", "response_generator"]
        
    else:
        plan = ["rag_retriever", "response_generator"]
    
    state["plan"] = plan
    state["completed_steps"] = state.get("completed_steps", []) + ["planning"]
    print(f"   Plan: {' -> '.join(plan)}")
    return state


def email_scanner_node(state: AgentState) -> AgentState:
    print(f"\n📧 EMAIL SCANNER: Scanning inbox...")    
    try:
        llm = LLMInterface(settings.OPENAI_API_KEY, settings.GEMINI_MODEL)
        
        current_date_str = datetime.now().strftime("%Y-%m-%d")
        scan_params = llm.generate_scan_parameters(
            user_query=state["user_query"],
            current_date=current_date_str
        )
        
        print(f"   Generated Query: {scan_params['gmail_query']}")
        
        days = state["entities"].get("scan_days", scan_params.get("days", 30))
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")
        
        result = scan_emails.invoke({
            "date_from": date_from,
            "date_to": date_to,
            "custom_query": scan_params['gmail_query'],
            "user_query": state["user_query"],
            "max_results": settings.EMAIL_SCAN_MAX_RESULTS,
            "require_attachments": scan_params.get("require_attachments", True),
            "use_filtering": True
        })
        
        if result.get("success"):
            state["email_scan_results"] = result
            
            if scan_params.get("require_attachments", True):
                state["downloaded_files"] = [
                    att["filepath"] for email in result.get("results", []) for att in email.get("attachments", [])
                ]
            else:
                state["downloaded_files"] = []
                
            print(f"   Found {result.get('filtered_count', 0)} relevant emails (filtered {result.get('filtered_out', 0)})")
        else:
            state["errors"] = state.get("errors", []) + [f"Scan failed: {result.get('error')}"]
            
    except Exception as e:
        print(f"   ❌ Error in intelligent scan: {e}")
        state["errors"] = state.get("errors", []) + [f"Scanner Error: {str(e)}"]
    
    state["completed_steps"] = state.get("completed_steps", []) + ["email_scanner"]
    return state


def pdf_processor_node(state: AgentState) -> AgentState:
    print(f"\n📄 PDF PROCESSOR: Processing documents...")
    downloaded_files = state.get("downloaded_files", [])
    parse_results = []
    
    for pdf_path in downloaded_files:
        if pdf_path.endswith('.pdf'):
            result = parse_pdf.invoke({"pdf_path": pdf_path, "use_ocr": False})
            if result.get("success"):
                parse_results.append(result)
            else:
                state["errors"].append(f"Failed parsing {os.path.basename(pdf_path)}")
    
    state["pdf_parse_results"] = parse_results
    state["completed_steps"] = state.get("completed_steps", []) + ["pdf_processor"]
    print(f"   Processed {len(parse_results)} PDFs")
    return state


def data_extractor_node(state: AgentState) -> AgentState:
    print(f"\n🔍 DATA EXTRACTOR: extracting info...")
    scan_type = state["entities"].get("email_scan_type", "bills")
    extracted_items = []
    
    for pdf in state.get("pdf_parse_results", []):
        if pdf.get("extracted_text"):
            result = extract_data.invoke({
                "text": pdf["extracted_text"],
                "extraction_type": scan_type
            })
            if result.get("success"):
                data = result["extracted_data"]
                data["source"] = pdf.get("file_path")
                extracted_items.append(data)

    if not extracted_items and state.get("email_scan_results"):
        emails = state["email_scan_results"].get("results", [])
        print(f"   Checking {len(emails)} email bodies...")
        for email in emails:
            result = extract_data.invoke({
                "text": email["body"],
                "extraction_type": scan_type
            })
            if result.get("success"):
                data = result["extracted_data"]
                data["source"] = f"Email: {email['subject']}"
                extracted_items.append(data)
                
    state["extracted_bills"] = extracted_items
    state["completed_steps"] = state.get("completed_steps", []) + ["data_extractor"]
    print(f"   Extracted {len(extracted_items)} items")
    return state


def database_saver_node(state: AgentState) -> AgentState:
    print(f"\n💾 RAG SAVER: Indexing items...")
    saved_ids = []
    
    for item in state.get("extracted_bills", []):
        result = save_bill.invoke({"bill_data": item})
        if result.get("success"):
            saved_ids.append(result.get("document_id", "unknown"))
            
    for pdf in state.get("pdf_parse_results", []):
        if pdf.get("extracted_text"):
            add_to_rag.invoke({
                "text": pdf["extracted_text"],
                "metadata": {"type": "raw_document", "path": pdf.get("file_path")}
            })

    state["saved_bill_ids"] = saved_ids
    state["completed_steps"] = state.get("completed_steps", []) + ["database_saver"]
    return state


def rag_indexer_node(state: AgentState) -> AgentState:
    state["completed_steps"] = state.get("completed_steps", []) + ["rag_indexer"]
    return state


def rag_retriever_node(state: AgentState) -> AgentState:
    print(f"\n🔎 RAG RETRIEVER: Searching...")
    res = rag_search.invoke({"query": state["user_query"]})
    if res.get("success"):
        state["retrieved_documents"] = res.get("results", [])
    state["completed_steps"] = state.get("completed_steps", []) + ["rag_retriever"]
    return state


def database_query_node(state: AgentState) -> AgentState:
    print(f"\n🔎 HISTORY QUERY: Searching RAG...")
    res = query_database.invoke({"query_type": "upcoming"}) 
    if res.get("success"):
        state["database_results"] = res
    state["completed_steps"] = state.get("completed_steps", []) + ["database_query"]
    return state


def web_searcher_node(state: AgentState) -> AgentState:
    print(f"\n🌐 WEB SEARCHER: Searching...")
    res = web_search.invoke({"query": state["user_query"]})
    if res.get("success"):
        state["web_search_results"] = res.get("results", [])
    state["completed_steps"] = state.get("completed_steps", []) + ["web_searcher"]
    return state


def reminder_creator_node(state: AgentState) -> AgentState:
    state["completed_steps"] = state.get("completed_steps", []) + ["reminder_creator"]
    return state


def response_generator_node(state: AgentState) -> AgentState:
    print(f"\n💬 RESPONSE GENERATOR: Crafting response...")
    from src.modules.llm_interface import LLMInterface
    
    context = {
        "intent": state.get("intent"),
        "scan_type": state["entities"].get("email_scan_type"),
        "extracted_items": state.get("extracted_bills", []),
        "rag_results": state.get("retrieved_documents") or state.get("database_results"),
        "errors": state.get("errors", [])
    }
    
    llm = LLMInterface(settings.GOOGLE_API_KEY, settings.GEMINI_MODEL)
    result = llm.generate_response(state["user_query"], context)
    
    state["final_response"] = result.get("response", "Error generating response")
    state["completed_steps"] = state.get("completed_steps", []) + ["response_generator"]
    return state


def error_handler_node(state: AgentState) -> AgentState:
    state["final_response"] = f"Errors encountered: {state['errors']}"
    return state


def route_after_intent(state: AgentState) -> str:
    return "error_handler" if state["intent"] == "unknown" else "planner"


def route_after_plan(state: AgentState) -> str:
    return state["plan"][0] if state["plan"] else "response_generator"


def should_continue(state: AgentState) -> str:
    plan = state["plan"]
    completed = state["completed_steps"]
    for step in plan:
        if step not in completed:
            return step
    return "end"