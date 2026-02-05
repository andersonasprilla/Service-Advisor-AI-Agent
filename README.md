# Rick Case Honda AI Service Agent

An intelligent Telegram bot that automates service advisor tasks using AI, RAG (Retrieval Augmented Generation), and customer database integration.

## 🌟 Features

### 1. **Technical Q&A with RAG**
- Answers questions from Honda vehicle manuals (Civic 2025, Ridgeline 2025, Passport 2026)
- Uses Pinecone vector database for semantic search
- Context-aware conversations (remembers which vehicle you're asking about)

### 2. **Smart Appointment Booking**
- Automated appointment scheduling via conversational flow
- **Returning customer detection** - recognizes customers from historical data
- Collects: name, phone, vehicle, service type, date, time
- Sends formatted notifications to service advisor
- Backs up appointments to JSON file

### 3. **Customer Database Integration**
- Loads historical service records from CSV files
- Instant lookup by phone number
- Shows customer history, previous vehicles, and visit count

### 4. **Intelligent Routing**
- Automatically detects which vehicle the customer is asking about
- Routes technical questions to the appropriate manual namespace
- Detects appointment intent vs technical questions

### 5. **Escalation Detection**
- Identifies frustrated customers or requests for human assistance
- Flags conversations for immediate attention

## 📁 Project Structure

```
rick-case-honda-ai/
├── main.py                 # Main Telegram bot with all handlers
├── tech_agent.py          # Technical Q&A agent (RAG)
├── booking_agent.py       # Appointment booking logic
├── customer_database.py   # Customer lookup system
├── router.py              # Intent classification
├── ingest.py              # Script to upload manuals to Pinecone
├── health_check.py        # Test Pinecone connection
├── reset_db.py           # Clear Pinecone namespaces
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
├── data/                 # Folder for CSV service records
│   └── RICKCASE_DAILY_SERVICE_RECORD_-_2021.csv
└── appointments.json     # Backup of all appointments
```

## 🚀 Setup Instructions

### 1. Prerequisites

- Python 3.8+
- Telegram account
- OpenAI API key
- Pinecone account

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Create Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow instructions
3. Save your bot token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 4. Get OpenAI API Key

1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Save it securely

### 5. Setup Pinecone

1. Create account at https://www.pinecone.io/
2. Create a new index with these settings:
   - **Name**: `honda-agent` (or your choice)
   - **Dimensions**: `1536`
   - **Metric**: `cosine`
   - **Cloud**: Any (AWS, GCP, Azure)
3. Save your API key

### 6. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
OPENAI_API_KEY=your_openai_api_key_here
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=honda-agent
SHOP_PASSWORD=HONDA2025
ADVISOR_TELEGRAM_ID=  # Leave empty initially
```

### 7. Prepare Customer Data

Place your CSV service records in the `data/` folder:

```bash
mkdir -p data
cp RICKCASE_DAILY_SERVICE_RECORD_-_2021.csv data/
```

**CSV Format Expected:**
```csv
TAG NO,RO#,YR/MAKE/MODEL,NAME,PHONE NO,DESCRIPTION OF SERVICE,WAIT/DROP ?
6895,503370,CIVIC 06,JOHN DOE,(954) 123-4567,OIL CHANGE,WAITER
```

### 8. Upload Vehicle Manuals to Pinecone

Place your PDF manuals in the project root folder:
- `civic_2025_manual.pdf`
- `ridgeline_2025_manual.pdf`
- `passport_2026_manual.pdf`

Then run the ingestion script:

```bash
# Ingest all manuals at once
python ingest.py

# Or ingest one at a time
python ingest.py civic_2025_manual.pdf civic-2025
python ingest.py ridgeline_2025_manual.pdf ridgeline-2025
python ingest.py passport_2026_manual.pdf passport-2026
```

**Note**: This will take 5-10 minutes per manual depending on size.

### 9. Test Pinecone Connection

```bash
python health_check.py
```

You should see:
```
✅ Found Score: 0.XX
   Content: [text from manual]...
```

### 10. Run the Bot

```bash
python main.py
```

You should see:
```
==================================================
🤖 RICK CASE HONDA AI BOT
==================================================
✅ Bot is running...
📊 Customer database: 1234 records loaded
👥 Unique customers: 567
📅 Smart appointment scheduling: ENABLED
🔄 Returning customer detection: ENABLED
⚠️  Advisor notifications: DISABLED (set ADVISOR_TELEGRAM_ID in .env)

Press Ctrl+C to stop
==================================================
```

### 11. Get Your Telegram User ID

1. Message your bot on Telegram
2. Check the console output:
   ```
   💡 TIP: Set ADVISOR_TELEGRAM_ID=123456789 in your .env file to receive notifications!
   ```
3. Copy that number and add it to your `.env` file:
   ```env
   ADVISOR_TELEGRAM_ID=123456789
   ```
4. Restart the bot

## 💬 How to Use

### For Customers

**Technical Questions:**
```
Customer: What's the oil capacity for my Civic?
Bot: The 2025 Honda Civic has an oil capacity of 3.7 quarts with filter...

Customer: How do I reset the maintenance light?
Bot: [Detailed instructions from manual]
```

**Book Appointment:**
```
Customer: I need to schedule an oil change
Bot: Great! What's your phone number?
Customer: 954-123-4567
Bot: 👋 Welcome back, John! I see you last brought in your Civic 25...
```

**First-Time Access:**
```
Customer: [Messages bot]
Bot: 🔐 Please send the shop password to begin.
Customer: HONDA2025
Bot: ✅ Access Granted! Welcome to Rick Case Honda!
```

### For Service Advisors

You'll receive formatted notifications like:

```
🔔 🔄 RETURNING APPOINTMENT REQUEST

👤 Customer: JOHN DOE
📞 Phone: (954) 123-4567
🚗 Vehicle: CIVIC 25
🔧 Service: Oil change
📅 Preferred Date: Tomorrow
⏰ Preferred Time: Morning

📊 Visit History: 3 previous visits
🚙 Previous Vehicles: CIVIC 25
🔧 Last Service: LOF/ROTATE

💬 Customer Telegram: @johndoe
🆔 User ID: 123456789

⚡ Action Required: Add to CDK/DMS manually
```

## 🔧 Maintenance

### Update Customer Database

Simply add new CSV files to the `data/` folder:
```bash
cp RICKCASE_DAILY_SERVICE_RECORD_-_2022.csv data/
```

Restart the bot to reload the database.

### Add New Vehicle Manual

```bash
python ingest.py accord_2024_manual.pdf accord-2024
```

Then update `main.py` to add the new vehicle to `VEHICLE_NAMESPACES` dict.

### Clear Pinecone Namespace (if needed)

```bash
python reset_db.py
```

Edit the script to specify which namespace to clear.

### View Appointments

All appointments are saved to `appointments.json` for backup and analysis.

## 📊 Architecture

```
Customer (Telegram)
        ↓
   [main.py] ← Authentication
        ↓
   [Router] ← Intent Detection
     ↙    ↘
Technical   Booking
    ↓         ↓
[RAG]    [Customer DB]
    ↓         ↓
Pinecone   CSV Files
```

**Flow:**
1. Customer messages bot via Telegram
2. Authentication check (password required)
3. Router determines intent (Technical vs Booking vs General)
4. Technical questions → RAG search in Pinecone → GPT-4 generates answer
5. Booking requests → Customer DB lookup → Conversation handler collects info
6. Advisor receives notification + JSON backup created

## 🎯 Key Features Explained

### RAG (Retrieval Augmented Generation)

Traditional approach:
```
User Question → GPT → Generic Answer (may hallucinate)
```

RAG approach:
```
User Question → Vector Search → Find Relevant Manual Sections → GPT + Context → Accurate Answer
```

Benefits:
- ✅ Answers grounded in actual manual content
- ✅ No hallucinations
- ✅ Always up-to-date (just re-upload manuals)
- ✅ Can cite specific page numbers

### Returning Customer Detection

When a customer provides their phone number:

```python
customer = customer_db.search_by_phone("954-123-4567")

if customer:
    # Found in historical records!
    {
        'name': 'JOHN DOE',
        'last_vehicle': 'CIVIC 25',
        'all_vehicles': ['CIVIC 25', 'ACCORD 18'],
        'last_service': 'OIL CHANGE',
        'visit_count': 3
    }
```

This enables:
- Personalized greeting
- Pre-filled vehicle information
- Faster booking process
- Service history context

### Namespace Organization

Pinecone namespaces keep data organized:

```
honda-agent (index)
    ├── civic-2025 (namespace)
    │   └── [1,000+ chunks from Civic manual]
    ├── ridgeline-2025 (namespace)
    │   └── [1,000+ chunks from Ridgeline manual]
    └── passport-2026 (namespace)
        └── [1,000+ chunks from Passport manual]
```

Benefits:
- Faster searches (smaller search space)
- Better accuracy (no cross-vehicle confusion)
- Easy to update individual manuals

## 🐛 Troubleshooting

### Bot not responding?

1. Check that the bot is running: `python main.py`
2. Verify your `TELEGRAM_BOT_TOKEN` in `.env`
3. Make sure you sent the password: `HONDA2025`

### "I couldn't find that in the manual"?

1. Test Pinecone connection: `python health_check.py`
2. Verify namespace exists: Check Pinecone dashboard
3. Re-ingest manual if needed: `python ingest.py civic_2025_manual.pdf civic-2025`

### Customer database not loading?

1. Check CSV files exist in `data/` folder
2. Verify CSV format matches expected columns
3. Check console output for errors

### Not receiving appointment notifications?

1. Verify `ADVISOR_TELEGRAM_ID` is set in `.env`
2. Make sure it's YOUR Telegram user ID (check console)
3. Restart the bot after changing `.env`

## 📝 TODO / Future Enhancements

- [ ] Add SMS notifications via Twilio
- [ ] Integrate with CDK DMS API for automatic appointment creation
- [ ] Add appointment cancellation/rescheduling
- [ ] Multi-language support (Spanish)
- [ ] Voice message support
- [ ] Service estimate calculator
- [ ] Parts availability checker
- [ ] Loaner car request system
- [ ] Follow-up message automation
- [ ] Analytics dashboard

## 🔒 Security Notes

- **Never commit `.env` file** - contains sensitive API keys
- Bot requires password authentication before use
- Customer data stored locally (CSV files)
- Appointments backed up to local JSON file
- API keys should be rotated periodically
- Consider encrypting customer database at rest

## 📄 License

Proprietary - Rick Case Honda Internal Use Only

## 👥 Support

For issues or questions, contact:
- **Developer**: [Your Name]
- **Service Manager**: [Manager Name]
- **IT Support**: [IT Contact]

---

**Last Updated**: February 2026
**Version**: 1.0.0
