from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import Dict, Optional, List, Type
import json


# --- Data Models ---

class BillData(BaseModel):
    """Structured data for bills and invoices"""
    vendor: Optional[str] = Field(description="Company or vendor name")
    amount: Optional[float] = Field(description="Total amount due")
    currency: str = Field(default="USD", description="Currency code")
    due_date: Optional[str] = Field(description="Due date in YYYY-MM-DD format")
    bill_date: Optional[str] = Field(description="Invoice date in YYYY-MM-DD format")
    category: Optional[str] = Field(description="Category (utility, subscription, etc.)")
    invoice_number: Optional[str] = Field(description="Invoice or account number")
    line_items: List[str] = Field(default=[], description="Summary of main line items")


class PromotionData(BaseModel):
    """Structured data for marketing emails and offers"""
    vendor: str = Field(description="Company offering the promotion")
    promo_code: Optional[str] = Field(description="Discount code if available")
    discount_details: str = Field(description="Description of the discount (e.g., '50% off')")
    expiration_date: Optional[str] = Field(description="Expiration date YYYY-MM-DD")
    product_category: Optional[str] = Field(description="What products are on sale")


class OrderData(BaseModel):
    """Structured data for order confirmations"""
    vendor: str = Field(description="Store name")
    order_number: Optional[str] = Field(description="Order ID")
    order_date: Optional[str] = Field(description="Date of purchase YYYY-MM-DD")
    total_amount: Optional[float] = Field(description="Total cost")
    items: List[str] = Field(description="List of items purchased")
    delivery_status: Optional[str] = Field(description="Estimated delivery or status")


class GeneralData(BaseModel):
    """Fallback for unknown types"""
    summary: str = Field(description="Brief summary of the email content")
    key_dates: List[str] = Field(default=[], description="Any important dates mentioned")
    entities: List[str] = Field(default=[], description="Names of companies or people")


class IntentClassification(BaseModel):
    """User intent classification"""
    intent: str = Field(description="Primary intent")
    scan_type: Optional[str] = Field(description="Email type if scanning")
    confidence: float = Field(description="Confidence score 0-1")
    entities: Dict = Field(default={}, description="Extracted parameters")


class RelevanceEvaluation(BaseModel):
    """Document relevance evaluation"""
    is_relevant: bool = Field(description="Whether document is relevant")
    relevance_score: float = Field(description="Score 0-1")
    reasoning: str = Field(description="Explanation")


class LLMInterface:
    
    def __init__(self, api_key: str, model: str = "", temperature: float = 0.1):
        self.model_name = model
        self.temperature = temperature
        self.llm = ChatOpenAI(model=model, api_key=api_key, temperature=temperature)
        
        self.extraction_registry = {
            "bills": BillData, "invoice": BillData,
            "promotions": PromotionData, "discounts": PromotionData,
            "orders": OrderData, "receipts": OrderData, "shipping": OrderData,
            "general": GeneralData
        }

    def _get_model_for_type(self, extraction_type: str) -> Type[BaseModel]:
        return self.extraction_registry.get(extraction_type.lower(), GeneralData)
        
    def extract_data(self, text: str, extraction_type: str = "bills") -> Dict:
        pydantic_model = self._get_model_for_type(extraction_type)
        parser = PydanticOutputParser(pydantic_object=pydantic_model)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"Extract {extraction_type} data."),
            ("human", "{format_instructions}\n\nText:\n{text}\n\nProvide data:")
        ])
        
        chain = prompt | self.llm | parser
        
        try:
            result = chain.invoke({"text": text, "format_instructions": parser.get_format_instructions()})
            return {"success": True, "extracted_data": result.dict(), "type": extraction_type}
        except Exception as e:
            return {"success": False, "error": str(e), "extracted_data": {}}
    
    def classify_intent(self, user_query: str) -> Dict:
        """CRITICAL: Distinguish scan_emails (fetch from Gmail) vs query_history (search DB)"""
        parser = PydanticOutputParser(pydantic_object=IntentClassification)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an intent classifier. CRITICAL DISTINCTION:

**scan_emails** = Fetch NEW emails from Gmail
  Triggers: "scan", "check", "get", "fetch", "find", "search my inbox"
  Examples: "Scan for university emails", "Get emails from last week"

**query_history** = Search ALREADY SCANNED emails in database
  Triggers: "what", "show", "tell me", "do I have", "did you find", "got", "is there"
  Examples: "What emails did you find?", "Do I have any Germany emails?"

For scan_emails, extract scan_type: bills, promotions, universities, orders, general
For query_history, extract search keywords to entities"""),
            ("human", "{format_instructions}\n\nQuery: {query}\n\nClassify:")
        ])
        
        chain = prompt | self.llm | parser
        
        try:
            result = chain.invoke({"query": user_query, "format_instructions": parser.get_format_instructions()})
            entities = result.entities
            if result.scan_type:
                entities['email_scan_type'] = result.scan_type
            return {"success": True, "intent": result.intent, "confidence": result.confidence, "entities": entities}
        except Exception as e:
            return {"success": False, "error": str(e), "intent": "unknown", "confidence": 0.0, "entities": {}}
    
    def generate_response(self, user_query: str, context: Dict, system_prompt: Optional[str] = None) -> Dict:
        if not system_prompt:
            system_prompt = "You are a helpful email assistant. Summarize emails clearly with sender, subject, date."
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Context:\n{context}\n\nQuestion: {query}\n\nResponse:")
        ])
        
        chain = prompt | self.llm
        
        try:
            result = chain.invoke({"context": json.dumps(context, indent=2, default=str), "query": user_query})
            return {"success": True, "response": result.content}
        except Exception as e:
            return {"success": False, "error": str(e), "response": "Error generating response."}
            
    def evaluate_relevance(self, query: str, document: str) -> Dict:
        parser = PydanticOutputParser(pydantic_object=RelevanceEvaluation)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Evaluate if email (sender, subject, body) is relevant to query. Be intelligent."),
            ("human", "{format_instructions}\n\nQuery: {query}\n\nDocument: {document}\n\nEvaluate:")
        ])
        
        chain = prompt | self.llm | parser
        
        try:
            result = chain.invoke({"query": query, "document": document, "format_instructions": parser.get_format_instructions()})
            return {"success": True, "is_relevant": result.is_relevant, "relevance_score": result.relevance_score, "reasoning": result.reasoning}
        except Exception as e:
            return {"success": False, "error": str(e), "is_relevant": False, "relevance_score": 0.0, "reasoning": "Error"}