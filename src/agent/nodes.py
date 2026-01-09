from src.agent.state import AgentState
from src.agent.tools import (
    classify_intent, scan_emails, parse_pdf, extract_data,
    save_bill, add_to_rag, rag_search, query_database,
    web_search, create_reminder
)
from datetime import datetime, timedelta
import os
import json
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
        
        scan_type = state["entities"].get("email_scan_type", "general")
        state["completed_steps"] = state.get("completed_steps", []) + ["intent_classification"]
        print(f"   Intent: {state['intent']} | Type: {scan_type} | Confidence: {state['intent_confidence']:.2f}")
    else:
        state["errors"] = state.get("errors", []) + [f"Intent failed: {result.get('error')}"]
        state["intent"] = "unknown"
    return state


def planner_node(state: AgentState) -> AgentState:
    print(f"\n📋 PLANNER: Creating execution plan...")
    intent = state["intent"]
    
    plan = []
    
    if intent == "scan_emails":
        # Full pipeline: Gmail → Extract → Save to DB
        plan = ["email_scanner", "pdf_processor", "data_extractor", "database_saver", "response_generator"]
        print(f"   📧 Will fetch NEW emails from Gmail and save to DB")
            
    elif intent == "query_history":
        # Search existing DB only (NO Gmail!)
        plan = ["rag_retriever", "response_generator"]
        print(f"   🔍 Will search EXISTING database (no Gmail scan)")
        
    elif intent == "analyze_spending":
        plan = ["database_query", "response_generator"]
        
    elif intent == "set_reminder":
        plan = ["database_query", "reminder_creator", "response_generator"]
        
    elif intent == "find_alternatives":
        plan = ["database_query", "web_searcher", "response_generator"]
        
    elif intent == "manual_add":
        plan = ["data_extractor", "database_saver", "response_generator"]
        
    else:
        # Default: search existing data
        plan = ["rag_retriever", "response_generator"]
        print(f"   🔍 Default: Searching database")
    
    state["plan"] = plan
    state["completed_steps"] = state.get("completed_steps", []) + ["planning"]
    print(f"   Plan: {' → '.join(plan)}")
    return state


def email_scanner_node(state: AgentState) -> AgentState:
    print(f"\n📧 EMAIL SCANNER: Fetching from Gmail...")    
    try:
        days = state["entities"].get("scan_days", 30)
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")
        
        scan_type = state["entities"].get("email_scan_type", "general")
        require_attachments = scan_type in ["bills", "invoice", "receipts", "orders"]
        
        print(f"   Date range: {date_from} to {date_to}")
        print(f"   Type: {scan_type} | Attachments: {require_attachments}")
        
        result = scan_emails.invoke({
            "date_from": date_from,
            "date_to": date_to,
            "user_query": state["user_query"],
            "user_email": settings.EMAIL_ADDRESS,
            "max_results": settings.EMAIL_SCAN_MAX_RESULTS,
            "require_attachments": require_attachments,
            "use_filtering": True
        })
        
        if result.get("success"):
            state["email_scan_results"] = result
            
            if require_attachments:
                state["downloaded_files"] = [
                    att["filepath"] for email in result.get("results", []) 
                    for att in email.get("attachments", [])
                ]
            else:
                state["downloaded_files"] = []
                
            print(f"   ✅ Found {result.get('filtered_count', 0)} relevant emails")
            print(f"   ⊗ Filtered out {result.get('filtered_out', 0)} irrelevant emails")
        else:
            state["errors"] = state.get("errors", []) + [f"Scan failed: {result.get('error')}"]
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        state["errors"] = state.get("errors", []) + [f"Scanner Error: {str(e)}"]
    
    state["completed_steps"] = state.get("completed_steps", []) + ["email_scanner"]
    return state


def pdf_processor_node(state: AgentState) -> AgentState:
    print(f"\n📄 PDF PROCESSOR: Processing attachments...")
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
    print(f"\n🔍 DATA EXTRACTOR: Extracting structured data...")
    scan_type = state["entities"].get("email_scan_type", "general")
    extracted_items = []
    
    # Extract from PDFs
    for pdf in state.get("pdf_parse_results", []):
        if pdf.get("extracted_text"):
            result = extract_data.invoke({"text": pdf["extracted_text"], "extraction_type": scan_type})
            if result.get("success"):
                data = result["extracted_data"]
                data["source"] = pdf.get("file_path")
                extracted_items.append(data)

    # Extract from email bodies
    if not extracted_items and state.get("email_scan_results"):
        emails = state["email_scan_results"].get("results", [])
        print(f"   Extracting from {len(emails)} email bodies...")
        for email in emails:
            result = extract_data.invoke({"text": email["body"], "extraction_type": scan_type})
            if result.get("success"):
                data = result["extracted_data"]
                data["source"] = f"Email: {email['subject']}"
                extracted_items.append(data)
                
    state["extracted_bills"] = extracted_items
    state["completed_steps"] = state.get("completed_steps", []) + ["data_extractor"]
    print(f"   ✅ Extracted {len(extracted_items)} items")
    return state


def database_saver_node(state: AgentState) -> AgentState:
    print(f"\n💾 DATABASE SAVER: Indexing to Vector DB...")
    saved_ids = []
    scan_type = state["entities"].get("email_scan_type", "general")
    
    # Save extracted structured data
    for item in state.get("extracted_bills", []):
        result = save_bill.invoke({"bill_data": item})
        if result.get("success"):
            saved_ids.append(result.get("document_id", "unknown"))
    
    # CRITICAL: Save STRUCTURED email metadata to Vector DB
    if state.get("email_scan_results"):
        emails = state["email_scan_results"].get("results", [])
        print(f"   Indexing {len(emails)} emails with structured metadata...")
        
        for email in emails:
            # Create structured JSON for each email
            email_doc = {
                "type": "email",
                "category": scan_type,
                "sender": email.get("sender", ""),
                "subject": email.get("subject", ""),
                "date": email.get("date", ""),
                "body_preview": email.get("body", "")[:500],
                "summary": f"Email from {email.get('sender', '')} about {email.get('subject', '')}",
                "has_attachments": len(email.get("attachments", [])) > 0
            }
            
            # Create searchable text content
            text_content = f"""
EMAIL DOCUMENT
==============
From: {email_doc['sender']}
Subject: {email_doc['subject']}
Date: {email_doc['date']}
Category: {email_doc['category']}

Summary: {email_doc['summary']}

Body:
{email.get('body', '')[:1000]}
"""
            
            # Save to vector DB
            result = add_to_rag.invoke({
                "text": text_content,
                "metadata": email_doc
            })
            
            if result.get("success"):
                saved_ids.append(result.get("document_id", ""))
                print(f"   ✓ Indexed: {email.get('subject', '')[:50]}")
    
    # Save raw PDF content
    for pdf in state.get("pdf_parse_results", []):
        if pdf.get("extracted_text"):
            add_to_rag.invoke({
                "text": pdf["extracted_text"],
                "metadata": {"type": "pdf", "path": pdf.get("file_path")}
            })

    state["saved_bill_ids"] = saved_ids
    state["completed_steps"] = state.get("completed_steps", []) + ["database_saver"]
    print(f"   ✅ Total indexed: {len(saved_ids)} documents")
    return state


def rag_indexer_node(state: AgentState) -> AgentState:
    state["completed_steps"] = state.get("completed_steps", []) + ["rag_indexer"]
    return state


def rag_retriever_node(state: AgentState) -> AgentState:
    print(f"\n🔎 RAG RETRIEVER: Searching Vector DB...")
    print(f"   Query: {state['user_query']}")
    
    try:
        # Search with higher top_k to get more results
        res = rag_search.invoke({"query": state["user_query"], "top_k": 10})
        
        if res.get("success"):
            results = res.get("results", [])
            
            # Clean and format results to avoid serialization issues
            cleaned_results = []
            for doc in results:
                cleaned_doc = {
                    "id": str(doc.get("id", "")),
                    "text": doc.get("text", ""),
                    "metadata": doc.get("metadata", {}),
                    "relevance_score": float(doc.get("relevance_score", 0))
                }
                cleaned_results.append(cleaned_doc)
            
            state["retrieved_documents"] = cleaned_results
            print(f"   ✅ Found {len(cleaned_results)} relevant documents")
            
            # Log what was found
            for i, doc in enumerate(cleaned_results[:3], 1):
                metadata = doc.get("metadata", {})
                if metadata.get("type") == "email":
                    subject = metadata.get("subject", "No subject")[:50]
                    score = doc.get("relevance_score", 0)
                    print(f"      {i}. {subject} (Score: {score:.2f})")
        else:
            print(f"   ❌ Search failed: {res.get('error', 'Unknown error')}")
            state["retrieved_documents"] = []
    
    except Exception as e:
        print(f"   ❌ Exception in RAG retriever: {e}")
        import traceback
        traceback.print_exc()
        state["retrieved_documents"] = []
        state["errors"] = state.get("errors", []) + [f"RAG retriever error: {str(e)}"]
    
    state["completed_steps"] = state.get("completed_steps", []) + ["rag_retriever"]
    return state


def database_query_node(state: AgentState) -> AgentState:
    print(f"\n🔎 DATABASE QUERY: Searching...")
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
    
    try:
        # Validate API key
        if not settings.OPENAI_API_KEY:
            error_msg = "OPENAI_API_KEY not set in environment"
            print(f"   ❌ {error_msg}")
            state["final_response"] = f"Configuration error: {error_msg}"
            state["errors"] = state.get("errors", []) + [error_msg]
            state["completed_steps"] = state.get("completed_steps", []) + ["response_generator"]
            return state
        
        # Format retrieved documents to be serializable
        retrieved_docs = state.get("retrieved_documents", [])
        formatted_docs = []
        
        for doc in retrieved_docs:
            formatted_doc = {
                "metadata": doc.get("metadata", {}),
                "text": doc.get("text", "")[:500],  # Truncate long text
                "relevance_score": float(doc.get("relevance_score", 0))
            }
            formatted_docs.append(formatted_doc)
        
        # Build context from retrieved data
        context = {
            "intent": state.get("intent"),
            "scan_type": state["entities"].get("email_scan_type"),
            "extracted_items": state.get("extracted_bills", [])[:5],  # Limit to 5
            "retrieved_documents": formatted_docs[:10],  # Limit to 10
            "database_results": state.get("database_results"),
            "errors": state.get("errors", [])
        }
        
        print(f"   Context: {len(formatted_docs)} documents")
        print(f"   Using model: {settings.OPENAI_MODEL}")
        
        # Use OpenAI
        llm = LLMInterface(settings.OPENAI_API_KEY, settings.OPENAI_MODEL)
        result = llm.generate_response(state["user_query"], context)
        
        if result.get("success"):
            state["final_response"] = result.get("response", "No response generated")
            print(f"   ✅ Response generated")
        else:
            error_msg = result.get("error", "Unknown error")
            print(f"   ❌ LLM Error: {error_msg}")
            state["final_response"] = f"I found the documents but couldn't generate a response. Error: {error_msg}"
            state["errors"] = state.get("errors", []) + [f"Response generation failed: {error_msg}"]
    
    except Exception as e:
        print(f"   ❌ Exception in response generator: {e}")
        import traceback
        traceback.print_exc()
        state["final_response"] = f"Error generating response: {str(e)}"
        state["errors"] = state.get("errors", []) + [f"Response generator exception: {str(e)}"]
    
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