# Email Management Agent (Open Source)

A fully local, intelligent AI agent that manages your emails, scans for bills/universities/promotions, finds deals, and sends reminders. Built with LangGraph, OpenAI, and Voyage AI.

## 🚀 Features

- 📧 **Intelligent Email Scanning**: Connects to Gmail to find bills, invoices, promotions, university admissions, orders, and more
- 🧠 **RAG Memory with Structured Storage**: Stores emails as searchable JSON in ChromaDB Vector Database
- 🔍 **Smart Query vs Scan**: Knows when to fetch new emails vs search existing data
- 📄 **PDF Intelligence**: Extracts text and tables from PDF attachments with OCR fallback
- 💰 **Deal Finder**: Uses Web Search to find cheaper alternatives for subscriptions
- 🔔 **Multi-Channel Reminders**: Sends alerts via WhatsApp, Telegram, or Email
- 💬 **Natural Language Chat**: Ask questions like "What emails did I get from Germany?" or "Scan for university admissions"

## 🆕 What's New

- ✅ **OpenAI Powered**: Uses GPT-4o-mini for fast, cost-efficient processing
- ✅ **Agentic Workflow**: Automatically decides whether to scan Gmail or query the database
- ✅ **Structured Email Indexing**: Emails saved as JSON with metadata (sender, subject, category, date)
- ✅ **Multi-Type Support**: bills, promotions, universities, orders, shipping, banking, insurance, and more

## 🛠️ Installation

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/email-management-agent.git
cd email-management-agent
```

### 2. Install Dependencies

Requires Python 3.10+

```bash
pip install -r requirements.txt
```

### 3. Set Up Environment Variables

Create a `.env` file in the root directory:

```env
# ===== AI & Embeddings (Required) =====
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxx
VOYAGE_API_KEY=pa-xxxxxxxxxxxxx

# Optional: Override default model (default is gpt-4o-mini)
OPENAI_MODEL=gpt-4o-mini

# ===== Gmail Scanning (Required for Email features) =====
ENABLE_EMAIL_SCANNING=true
GMAIL_CREDENTIALS_PATH=credentials.json
EMAIL_ADDRESS=your_email@gmail.com

# ===== Email Notifications (Optional) =====
EMAIL_PASSWORD=your_gmail_app_password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587

# ===== WhatsApp Notifications (Optional) =====
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_FROM_NUMBER=whatsapp:+14155238886
TWILIO_TO_NUMBER=whatsapp:+1234567890

# ===== Telegram Notifications (Optional) =====
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# ===== Configuration =====
EMAIL_SCAN_MAX_RESULTS=50
DEFAULT_EMAIL_SCAN_TYPE=general
```

### 4. Set Up Gmail API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable **Gmail API**
4. Go to **Credentials** → **Create Credentials** → **OAuth Client ID**
5. Choose **Desktop App**
6. Download the JSON file and save it as `credentials.json` in the project root
7. On first run, you'll be prompted to authorize the app in your browser

### 5. Get API Keys

**OpenAI API Key:**
- Sign up at [OpenAI Platform](https://platform.openai.com/)
- Go to API Keys section
- Create new secret key

**Voyage AI API Key:**
- Sign up at [Voyage AI](https://www.voyageai.com/)
- Get your API key from dashboard

## 🏃 How to Run

### Interactive Chat Mode

```bash
python main.py
```

Example conversation:
```
You: Scan my inbox for university emails from Germany
Agent: [Scans Gmail, indexes 5 emails] Found 5 university emails...

You: What did you get from Germany?
Agent: [Searches database] I found 5 emails from German institutions...

You: Show me the Constructor University email
Agent: [Searches by keyword] Here's the email from Constructor University...
```

### Single Command Mode

```bash
python main.py --query "What emails did I get about scholarships?"
```

### Targeted Scanning

```bash
# Scan for university admission emails (last 90 days)
python main.py --scan-type universities --days 90

# Scan for bills (last 30 days)
python main.py --scan-type bills --days 30

# Scan for promotions (last 7 days)
python main.py --scan-type promotions --days 7
```

## 💬 Example Commands

### Scan Commands (Fetch from Gmail)
| Query | What Happens |
|-------|--------------|
| "Scan my inbox for university emails" | Fetches new emails from Gmail, indexes them |
| "Check for admission emails from Germany" | Scans Gmail with LLM filtering |
| "Get bills from last month" | Fetches and indexes bill-related emails |
| "Find promotion emails" | Scans for marketing offers |

### Query Commands (Search Database)
| Query | What Happens |
|-------|--------------|
| "What emails did you find from Germany?" | Searches indexed emails (no Gmail scan) |
| "Show me university emails" | Queries Vector DB |
| "Is there anything about scholarships?" | Semantic search through stored emails |
| "Do I have emails from Constructor?" | Searches by keyword |

### Other Commands
| Query | What Happens |
|-------|--------------|
| "Find cheaper alternatives to Netflix" | Web search for deals |
| "Analyze my spending on subscriptions" | Queries database and analyzes |
| "Remind me to pay rent" | Creates reminders |

## 🏗️ Architecture

### Agentic Workflow

```
User Query → Intent Classifier → Planner → Execute Plan → Response
```

**Intent Classification:**
- `scan_emails`: Fetch NEW emails from Gmail
- `query_history`: Search EXISTING database (no Gmail scan)
- `analyze_spending`: Analyze financial data
- `find_alternatives`: Web search for deals
- `set_reminder`: Create reminders

### Email Processing Pipeline

```
Gmail API → LLM Filtering → PDF Extraction → Data Structuring → Vector DB
```

1. **Email Scanner**: Fetches emails, applies LLM-based relevance filtering
2. **PDF Processor**: Extracts text from attachments (PyPDF2 → pdfplumber → OCR)
3. **Data Extractor**: Uses OpenAI to extract structured data (vendor, amount, date)
4. **Database Saver**: Indexes emails as JSON with rich metadata

### Email Storage Format

Each email is stored with structured metadata:

```json
{
  "type": "email",
  "category": "universities",
  "sender": "graduateadmission@constructor.university",
  "subject": "Welcome to Constructor University",
  "date": "2026-01-07",
  "body_preview": "Dear Malik...",
  "summary": "University admission welcome email",
  "has_attachments": false
}
```

### Tech Stack

- **LLM**: OpenAI GPT-4o-mini (default) or GPT-4o
- **Embeddings**: Voyage AI (voyage-3-lite)
- **Vector DB**: ChromaDB (local, persistent)
- **Orchestration**: LangGraph
- **Email**: Gmail API
- **PDF Parsing**: PyPDF2, pdfplumber, pytesseract (OCR)

## 📁 Project Structure

```
email-management-agent/
├── src/
│   ├── agent/
│   │   ├── graph.py          # LangGraph workflow
│   │   ├── nodes.py          # Workflow nodes
│   │   ├── state.py          # Agent state
│   │   └── tools.py          # LangChain tools
│   ├── modules/
│   │   ├── email_scanner.py  # Gmail integration
│   │   ├── llm_interface.py  # OpenAI wrapper
│   │   ├── pdf_parser.py     # PDF extraction
│   │   └── rag_system.py     # Vector DB operations
│   └── config/
│       └── settings.py       # Configuration
├── data/
│   ├── raw/                  # Downloaded attachments
│   └── vector_store/         # ChromaDB storage
├── credentials.json          # Gmail OAuth
├── .env                      # API keys
└── main.py                   # Entry point
```

## 🔧 Supported Email Types

The agent can scan and categorize:

- 📄 **bills**: Utility bills, invoices, statements
- 🎓 **universities**: Admission emails, offers, assessments
- 🎁 **promotions**: Marketing offers, discounts
- 🛍️ **orders**: Purchase confirmations, receipts
- 📦 **shipping**: Tracking, delivery notifications
- 💳 **banking**: Statements, transaction alerts
- 🏥 **insurance**: Policies, claims
- ✈️ **travel**: Bookings, itineraries
- 📋 **tax**: Tax documents, 1099s, W-2s
- 📝 **general**: Anything else

## 💡 Tips

### Cost Optimization

**gpt-4o-mini** (default):
- Input: $0.15 / 1M tokens
- Output: $0.60 / 1M tokens
- Perfect for most queries

For complex queries, upgrade:
```env
OPENAI_MODEL=gpt-4o
```

### Email Filtering

The agent uses LLM to read FULL emails (sender + subject + body) and intelligently filter relevance. No keyword matching - pure AI comprehension.

### Query vs Scan

- Use **"scan"** when you want new data from Gmail
- Use **"what/show/do I have"** when querying existing data
- The agent automatically decides the right approach

## 🤝 Contributing

This is an open-source project! Contributions welcome:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes:
   - Add new tools in `src/agent/tools.py`
   - Improve prompts in `src/modules/llm_interface.py`
   - Add email types in `src/config/email_scan_config.py`
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## 🐛 Troubleshooting

### "Error generating response"
- Check that `OPENAI_API_KEY` is set correctly
- Verify the model name (default: `gpt-4o-mini`)
- Check API key balance at [OpenAI Platform](https://platform.openai.com/)

### "Gmail authentication failed"
- Ensure `credentials.json` is in the root directory
- Delete `token.json` and re-authenticate
- Check that Gmail API is enabled in Google Cloud Console

### "No emails found"
- The LLM filter might be too strict
- Try setting `use_filtering=False` in email_scanner.py for debugging
- Check date range (default is last 30 days)

### "Vector DB error"
- Delete `data/vector_store/` directory
- Run again to recreate the database

## 📜 License

MIT License - See [LICENSE](LICENSE) file for details

## 🙏 Acknowledgments

Built with:
- [LangGraph](https://github.com/langchain-ai/langgraph) - Agent orchestration
- [OpenAI](https://openai.com/) - Language models
- [Voyage AI](https://www.voyageai.com/) - Embeddings
- [ChromaDB](https://www.trychroma.com/) - Vector database
- [Gmail API](https://developers.google.com/gmail/api) - Email access

---

**⭐ Star this repo if you find it useful!**

For questions or issues, open an [Issue](https://github.com/your-username/email-management-agent/issues) or [Discussion](https://github.com/your-username/email-management-agent/discussions).