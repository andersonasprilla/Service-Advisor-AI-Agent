import os
import re
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from datetime import datetime
import json
import shutil

from pinecone import Pinecone
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from customer_database import CustomerDatabase

load_dotenv()

# --- SETUP DATA FOLDER ---
def setup_data_folder():
    """Copy CSV files from uploads to data folder if needed"""
    data_folder = "./data"
    uploads_folder = "/mnt/user-data/uploads"
    
    if not os.path.exists(data_folder):
        os.makedirs(data_folder, exist_ok=True)
        print(f"✅ Created data folder: {data_folder}")
    
    if os.path.exists(uploads_folder):
        csv_files = [f for f in os.listdir(uploads_folder) if f.startswith("RICKCASE_") and f.endswith(".csv")]
        for csv_file in csv_files:
            src = os.path.join(uploads_folder, csv_file)
            dst = os.path.join(data_folder, csv_file)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                print(f"✅ Copied {csv_file} to data folder")

setup_data_folder()

# Load customer database
customer_db = CustomerDatabase(csv_folder="./data")

# --- CONVERSATION STATES for Appointment Booking ---
CONFIRM_IDENTITY, ASKING_PHONE, ASKING_VEHICLE, ASKING_SERVICE, ASKING_DATE, ASKING_TIME = range(6)

# --- MEMORY STORAGE ---
user_sessions = {}  # Stores vehicle context for technical questions
appointment_data = {}  # Stores partial appointment info during booking

# --- AUTHENTICATION ---
allowed_users = []  # Telegram user IDs that have been authenticated
SHOP_PASSWORD = os.getenv("SHOP_PASSWORD", "HONDA2025")

# --- YOUR TELEGRAM ID (Set this to receive notifications) ---
ADVISOR_TELEGRAM_ID = os.getenv("ADVISOR_TELEGRAM_ID")
if ADVISOR_TELEGRAM_ID:
    ADVISOR_TELEGRAM_ID = int(ADVISOR_TELEGRAM_ID)

# --- SETUP ---
try:
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    pinecone_index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "honda-agent"))
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    print("✅ AI services initialized successfully")
except Exception as e:
    print(f"⚠️ Warning: Could not initialize AI services: {e}")
    embeddings = None
    pinecone_index = None
    llm = None

# --- VEHICLE NAMESPACE MAPPING ---
VEHICLE_NAMESPACES = {
    "passport": "passport-2026",
    "civic": "civic-2025",
    "ridgeline": "ridgeline-2025"
}

# --- 1. THE ROUTER ---
def identify_vehicle(user_text: str):
    """Identify which Honda vehicle the user is asking about"""
    if not llm:
        # Fallback: keyword matching
        user_lower = user_text.lower()
        if "passport" in user_lower:
            return "passport-2026"
        elif "civic" in user_lower:
            return "civic-2025"
        elif "ridgeline" in user_lower:
            return "ridgeline-2025"
        return "unknown"
    
    try:
        system_prompt = """
        You are a router for a Honda AI. 
        Analyze the user's question and identify if they explicitly mention a car model.
        
        - If they mention a Passport, return: passport
        - If they mention a Civic, return: civic
        - If they mention a Ridgeline, return: ridgeline
        - If they do NOT mention a car, return: unknown
        
        Return ONLY the string (lowercase, just the car name).
        """
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{text}")])
        chain = prompt | llm | StrOutputParser()
        result = chain.invoke({"text": user_text}).strip().lower()
        
        # Map to namespace
        if result in VEHICLE_NAMESPACES:
            return VEHICLE_NAMESPACES[result]
        elif result in ["passport-2026", "civic-2025", "ridgeline-2025"]:
            return result
        
        return "unknown"
    except Exception as e:
        print(f"❌ Error in identify_vehicle: {e}")
        return "unknown"

# --- 2. THE GUARD ---
def check_for_escalation(user_text: str):
    """Check if the user is angry or asking for a human"""
    if not llm:
        return "NO"
    
    try:
        system_prompt = """
        You are a customer service supervisor. Analyze the user's incoming text.
        
        Return "YES" if:
        1. The user is expressing anger or frustration (swearing, shouting).
        2. The user explicitly asks for a "human", "person", "agent", or "manager".
        
        Return "NO" if:
        1. It is a normal technical question.
        2. They are just saying hello or giving car info.
        
        Return ONLY "YES" or "NO".
        """
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{text}")])
        chain = prompt | llm | StrOutputParser()
        return chain.invoke({"text": user_text}).strip()
    except Exception as e:
        print(f"❌ Error in check_for_escalation: {e}")
        return "NO"

# --- 3. INTENT DETECTOR ---
def detect_appointment_intent(user_text: str):
    """Check if the user wants to schedule an appointment"""
    if not llm:
        # Fallback to keyword detection
        keywords = ["book", "schedule", "appointment", "service", "oil change", "maintenance", "bring my car"]
        return "YES" if any(keyword in user_text.lower() for keyword in keywords) else "NO"
    
    try:
        system_prompt = """
        Analyze if the user wants to schedule a service appointment.
        
        Return "YES" if they mention:
        - "book", "schedule", "appointment", "make an appointment"
        - "service appointment", "get my car serviced"
        - "need an oil change", "need maintenance"
        - "come in", "bring my car in"
        
        Return "NO" if they're just asking questions about their car.
        
        Return ONLY "YES" or "NO".
        """
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{text}")])
        chain = prompt | llm | StrOutputParser()
        return chain.invoke({"text": user_text}).strip()
    except Exception as e:
        print(f"❌ Error in detect_appointment_intent: {e}")
        return "NO"

# --- 4. PHONE NUMBER EXTRACTOR ---
def extract_phone_from_text(user_text: str):
    """
    Extract phone number with regex fallback (more reliable than LLM alone)
    """
    # First try regex (most reliable)
    patterns = [
        r'\(\d{3}\)\s*\d{3}[-\s]?\d{4}',  # (954) 243-1238
        r'\d{3}[-.\s]\d{3}[-.\s]\d{4}',    # 954-243-1238 or 954.243.1238
        r'\b\d{10}\b',                      # 9542431238 (exactly 10 digits)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, user_text)
        if match:
            phone = match.group()
            # Normalize to (XXX) XXX-XXXX format to match CSV
            digits = re.sub(r'\D', '', phone)
            
            if len(digits) == 10:
                formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
                print(f"📞 Extracted phone via regex: {formatted}")
                return formatted
    
    # Fallback to LLM if regex fails
    if not llm:
        return None
    
    try:
        system_prompt = """
        Extract ONLY the phone number from the user's message.
        
        If you find a phone number, return it in format: (XXX) XXX-XXXX
        If NO phone number is found, return exactly: "NO_PHONE"
        
        Examples:
        "My number is 954-243-1238" → (954) 243-1238
        "Call me at 9542431238" → (954) 243-1238
        "I don't have one" → NO_PHONE
        """
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{text}")])
        chain = prompt | llm | StrOutputParser()
        result = chain.invoke({"text": user_text}).strip()
        
        if "NO_PHONE" in result:
            return None
        
        print(f"📞 Extracted phone via LLM: {result}")
        return result
        
    except Exception as e:
        print(f"❌ Error in extract_phone_from_text: {e}")
        return None

# --- 5. THE SEARCH (RAG) ---
def get_answer_from_manual(question: str, namespace: str):
    """Search vehicle manual and generate answer"""
    if not embeddings or not pinecone_index or not llm:
        return "I'm currently unable to access the technical manuals. Please try again later or contact service directly."
    
    try:
        print(f"🔎 Searching in namespace: [{namespace}] for: {question}")
        
        query_vector = embeddings.embed_query(question)
        
        search_results = pinecone_index.query(
            vector=query_vector,
            top_k=15, 
            include_metadata=True,
            namespace=namespace
        )
        
        if not search_results['matches']:
            return "NO_ANSWER_FOUND"
        
        context_text = ""
        for match in search_results['matches']:
            if 'text' in match['metadata']:
                context_text += match['metadata']['text'] + "\n---\n"
            
        prompt_template = ChatPromptTemplate.from_template("""
        You are a helpful Honda Service Advisor Assistant.
        Answer the customer's question ONLY based on the following manual context.
        
        If the answer is NOT in the context, reply exactly with: "NO_ANSWER_FOUND"
        
        Keep your answer concise and helpful. Use bullet points for clarity when appropriate.
        
        Context from Manual:
        {context}
        
        Customer Question:
        {question}
        """)
        
        chain = prompt_template | llm
        response = chain.invoke({
            "context": context_text, 
            "question": question
        })
        
        return response.content
    except Exception as e:
        print(f"❌ Error in get_answer_from_manual: {e}")
        return "I encountered an error searching the manual. Please try rephrasing your question."

# --- 6. APPOINTMENT NOTIFICATION ---
async def notify_advisor(context: ContextTypes.DEFAULT_TYPE, appointment_info: dict):
    """Send appointment notification to service advisor"""
    if not ADVISOR_TELEGRAM_ID:
        print("⚠️  WARNING: ADVISOR_TELEGRAM_ID not set. Cannot send notification.")
        print(f"📋 Appointment Details: {json.dumps(appointment_info, indent=2)}")
        return
    
    # Format the notification message
    returning = "🔄 RETURNING" if appointment_info.get('is_returning') else "🆕 NEW"
    
    message = f"""
🔔 {returning} APPOINTMENT REQUEST

👤 Customer: {appointment_info['name']}
📞 Phone: {appointment_info['phone']}
🚗 Vehicle: {appointment_info['vehicle']}
🔧 Service: {appointment_info['service_type']}
📅 Preferred Date: {appointment_info['preferred_date']}
⏰ Preferred Time: {appointment_info['preferred_time']}
"""
    
    if appointment_info.get('is_returning'):
        message += f"\n📊 Visit History: {appointment_info.get('visit_count', 0)} previous visits"
        if appointment_info.get('all_vehicles'):
            message += f"\n🚙 Previous Vehicles: {', '.join(appointment_info.get('all_vehicles', []))}"
        message += f"\n🔧 Last Service: {appointment_info.get('last_service', 'N/A')}"
    
    message += f"\n\n💬 Customer Telegram: @{appointment_info.get('telegram_username', 'N/A')}"
    message += f"\n🆔 User ID: {appointment_info['user_id']}"
    message += "\n\n⚡ Action Required: Add to CDK/DMS manually"
    
    try:
        await context.bot.send_message(
            chat_id=ADVISOR_TELEGRAM_ID,
            text=message
        )
        print(f"✅ Notification sent to advisor (ID: {ADVISOR_TELEGRAM_ID})")
    except Exception as e:
        print(f"❌ Failed to send notification: {e}")
        print(f"📋 Appointment Details: {json.dumps(appointment_info, indent=2)}")

def save_appointment_to_file(appointment_info: dict):
    """Backup: Save appointment to a JSON file with verification"""
    filename = "appointments.json"
    
    try:
        # Load existing appointments
        appointments = []
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    appointments = json.load(f)
                    print(f"📂 Loaded {len(appointments)} existing appointments")
            except Exception as e:
                print(f"⚠️  Could not load existing appointments: {e}")
                appointments = []
        
        # Add timestamp
        appointment_info['created_at'] = datetime.now().isoformat()
        
        # Append and save
        appointments.append(appointment_info)
        
        with open(filename, 'w') as f:
            json.dump(appointments, f, indent=2)
        
        print(f"✅ Appointment saved to {filename}")
        print(f"📊 Total appointments in file: {len(appointments)}")
        
        # Verify it was saved
        if os.path.exists(filename):
            file_size = os.path.getsize(filename)
            print(f"📄 File size: {file_size} bytes")
        
    except Exception as e:
        print(f"❌ ERROR saving appointment: {e}")
        print(f"📋 Appointment data: {json.dumps(appointment_info, indent=2)}")


# --- APPOINTMENT CONVERSATION HANDLERS ---

async def start_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the appointment booking process"""
    user_id = update.effective_user.id
    
    # Initialize appointment data with state tracking
    appointment_data[user_id] = {
        'user_id': user_id,
        'telegram_username': update.effective_user.username,
        '_state': 'ASKING_PHONE'  # Track current state
    }
    
    # Try to extract phone from message
    phone = extract_phone_from_text(update.message.text)
    
    if phone:
        # Check if customer exists
        customer = customer_db.search_by_phone(phone)
        
        if customer:
            # Returning customer!
            appointment_data[user_id].update({
                'name': customer['name'],
                'phone': customer['phone'],
                'is_returning': True,
                'visit_count': customer['visit_count'],
                'all_vehicles': customer['all_vehicles'],
                'last_service': customer['last_service']
            })
            
            await update.message.reply_text(
                f"👋 Welcome back, {customer['name']}!\n\n"
                f"I see you last brought in your {customer['last_vehicle']}.\n\n"
                f"Is this the vehicle you'd like to service today?\n"
                f"Reply 'yes' or tell me which vehicle."
            )
            return ASKING_VEHICLE
        else:
            # New customer with phone
            appointment_data[user_id]['phone'] = phone
            await update.message.reply_text(
                "Thanks! What's your name?"
            )
            return CONFIRM_IDENTITY
    
    # No phone number detected
    await update.message.reply_text(
        "📅 Great! Let me help you schedule an appointment.\n\n"
        "What's your phone number?"
    )
    return ASKING_PHONE

async def confirm_identity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect customer name"""
    user_id = update.effective_user.id
    appointment_data[user_id]['name'] = update.message.text.strip()
    appointment_data[user_id]['is_returning'] = False
    appointment_data[user_id]['_state'] = 'ASKING_VEHICLE'  # Update state
    
    await update.message.reply_text(
        "Perfect! What vehicle will you be bringing in?\n"
        "(e.g., '2024 Civic', 'Passport', '2022 Accord')"
    )
    
    return ASKING_VEHICLE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect phone number with detailed debugging"""
    user_id = update.effective_user.id
    user_text = update.message.text
    
    # DEBUG: Show what user entered
    print(f"\n{'='*60}")
    print(f"🔍 USER INPUT: '{user_text}'")
    print(f"{'='*60}")
    
    # Try to extract phone
    phone = extract_phone_from_text(user_text)
    
    # DEBUG: Show what was extracted
    print(f"📞 EXTRACTED PHONE: '{phone}'")
    
    if not phone:
        print(f"❌ No phone number found in input")
        await update.message.reply_text(
            "I couldn't find a phone number. Please send it in one of these formats:\n"
            "• (954) 243-1238\n"
            "• 954-243-1238\n"
            "• 9542431238"
        )
        return ASKING_PHONE
    
    # Check if customer exists in database
    print(f"🔎 SEARCHING DATABASE for: {phone}")
    customer = customer_db.search_by_phone(phone)
    
    if customer:
        # RETURNING CUSTOMER!
        print(f"✅ CUSTOMER FOUND!")
        print(f"   Name: {customer['name']}")
        print(f"   Last Vehicle: {customer['last_vehicle']}")
        print(f"   Visit Count: {customer['visit_count']}")
        print(f"{'='*60}\n")
        
        appointment_data[user_id].update({
            'name': customer['name'],
            'phone': customer['phone'],
            'is_returning': True,
            'visit_count': customer['visit_count'],
            'all_vehicles': customer['all_vehicles'],
            'last_service': customer['last_service'],
            '_state': 'ASKING_VEHICLE'  # Update state
        })
        
        await update.message.reply_text(
            f"👋 Welcome back, {customer['name']}!\n\n"
            f"I see you last brought in your {customer['last_vehicle']}.\n"
            f"You've been here {customer['visit_count']} time(s) before.\n\n"
            f"Is this the vehicle you'd like to service today?\n"
            f"Reply 'yes' or tell me which vehicle."
        )
        return ASKING_VEHICLE
    
    # NEW CUSTOMER
    print(f"❌ CUSTOMER NOT FOUND in database")
    print(f"{'='*60}\n")
    
    appointment_data[user_id]['phone'] = phone
    appointment_data[user_id]['is_returning'] = False
    appointment_data[user_id]['_state'] = 'CONFIRM_IDENTITY'  # Update state
    
    await update.message.reply_text("Thanks! What's your name?")
    return CONFIRM_IDENTITY

async def get_vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect vehicle information"""
    user_id = update.effective_user.id
    user_text = update.message.text.strip().lower()
    
    # Check if returning customer said "yes"
    if appointment_data[user_id].get('is_returning') and user_text in ['yes', 'yeah', 'yep', 'correct']:
        customer = customer_db.search_by_phone(appointment_data[user_id]['phone'])
        appointment_data[user_id]['vehicle'] = customer['last_vehicle']
    else:
        appointment_data[user_id]['vehicle'] = update.message.text
    
    appointment_data[user_id]['_state'] = 'ASKING_SERVICE'  # Update state
    
    await update.message.reply_text(
        "Thanks! What type of service do you need?\n\n"
        "Examples:\n"
        "• Oil change\n"
        "• Tire rotation\n"
        "• Brake inspection\n"
        "• General maintenance\n"
        "• Diagnostic/Check engine light\n"
        "• Recall service\n"
        "• Other (please describe)"
    )
    
    return ASKING_SERVICE

async def get_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect service type"""
    user_id = update.effective_user.id
    appointment_data[user_id]['service_type'] = update.message.text
    appointment_data[user_id]['_state'] = 'ASKING_DATE'  # Update state
    
    await update.message.reply_text(
        "Perfect! What date works best for you?\n"
        "(e.g., 'Tomorrow', 'February 10', 'Next Monday', 'This week')"
    )
    
    return ASKING_DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect preferred date"""
    user_id = update.effective_user.id
    appointment_data[user_id]['preferred_date'] = update.message.text
    appointment_data[user_id]['_state'] = 'ASKING_TIME'  # Update state
    
    await update.message.reply_text(
        "Great! What time would you prefer?\n"
        "(e.g., 'Morning', '10 AM', 'Afternoon', 'Anytime')"
    )
    
    return ASKING_TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect preferred time and finish booking"""
    user_id = update.effective_user.id
    appointment_data[user_id]['preferred_time'] = update.message.text
    
    # Get complete appointment info and remove internal state field
    appointment_info = appointment_data[user_id].copy()
    
    # Remove internal state field before saving
    if '_state' in appointment_info:
        del appointment_info['_state']
    
    print(f"\n{'='*60}")
    print(f"💾 SAVING APPOINTMENT")
    print(f"{'='*60}")
    print(f"Customer: {appointment_info.get('name')}")
    print(f"Phone: {appointment_info.get('phone')}")
    print(f"Vehicle: {appointment_info.get('vehicle')}")
    print(f"{'='*60}\n")
    
    # Save to file (backup)
    save_appointment_to_file(appointment_info)
    
    # Notify advisor
    await notify_advisor(context, appointment_info)
    
    # Confirm to customer
    confirmation = "✅ Appointment request received!\n\n📋 Summary:\n"
    confirmation += f"• Name: {appointment_info['name']}\n"
    confirmation += f"• Phone: {appointment_info['phone']}\n"
    confirmation += f"• Vehicle: {appointment_info['vehicle']}\n"
    confirmation += f"• Service: {appointment_info['service_type']}\n"
    confirmation += f"• Date: {appointment_info['preferred_date']}\n"
    confirmation += f"• Time: {appointment_info['preferred_time']}\n"
    
    if appointment_info.get('is_returning'):
        confirmation += f"\n👋 Thanks for coming back! (Visit #{appointment_info.get('visit_count', 0) + 1})"
    
    confirmation += "\n\n🔔 Your service advisor will confirm your appointment shortly!"
    confirmation += "\n\nIs there anything else I can help you with?"
    
    await update.message.reply_text(confirmation)
    
    # Clean up
    del appointment_data[user_id]
    
    return ConversationHandler.END

async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel appointment booking"""
    user_id = update.effective_user.id
    
    if user_id in appointment_data:
        del appointment_data[user_id]
    
    await update.message.reply_text(
        "❌ Appointment booking cancelled.\n\n"
        "Type 'book appointment' anytime you're ready to schedule!"
    )
    
    return ConversationHandler.END

# --- TELEGRAM HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command"""
    user_id = update.effective_user.id
    
    if user_id not in allowed_users:
        await update.message.reply_text(
            "👋 Welcome to Rick Case Honda Service AI!\n\n"
            "🔐 Please send the shop password to begin."
        )
    else:
        await update.message.reply_text(
            "👋 Welcome back to Rick Case Honda Service AI!\n\n"
            "💬 Ask me any Honda questions or type 'book appointment' to schedule service!"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /help command"""
    await update.message.reply_text(
        "🚗 Rick Case Honda Service AI\n\n"
        "I can help you with:\n\n"
        "📚 Technical Questions:\n"
        "• 2025 Honda Civic\n"
        "• 2025 Honda Ridgeline\n"
        "• 2026 Honda Passport\n\n"
        "📅 Quick Appointment Scheduling:\n"
        "• Say 'book appointment' or 'schedule service'\n"
        "• If you're a returning customer, I'll recognize you!\n"
        "• Much faster than calling!\n\n"
        "💡 Tips:\n"
        "• Just mention your car model in your question\n"
        "• Example: 'What's the oil capacity for my Civic?'\n"
        "• I'll remember which car you're asking about!\n\n"
        "Just ask me anything!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all text messages - FIXED VERSION"""
    user_id = update.effective_user.id
    user_text = update.message.text
    
    print(f"📩 Received from {user_id} (@{update.effective_user.username}): {user_text}")
    
    # Print user ID for first-time setup
    if not ADVISOR_TELEGRAM_ID:
        print(f"💡 TIP: Set ADVISOR_TELEGRAM_ID={user_id} in your .env file to receive notifications!")
    
    # CRITICAL FIX: Check if user is in appointment booking flow
    if user_id in appointment_data and '_state' in appointment_data[user_id]:
        current_state = appointment_data[user_id]['_state']
        print(f"🔄 User in appointment flow, state: {current_state}")
        
        if current_state == 'ASKING_PHONE':
            return await get_phone(update, context)
        elif current_state == 'CONFIRM_IDENTITY':
            return await confirm_identity(update, context)
        elif current_state == 'ASKING_VEHICLE':
            return await get_vehicle(update, context)
        elif current_state == 'ASKING_SERVICE':
            return await get_service(update, context)
        elif current_state == 'ASKING_DATE':
            return await get_date(update, context)
        elif current_state == 'ASKING_TIME':
            return await get_time(update, context)
    
    # 1. AUTH CHECK
    if user_id not in allowed_users:
        if user_text.strip().upper() == SHOP_PASSWORD:
            allowed_users.append(user_id)
            await update.message.reply_text(
                "✅ Access Granted! Welcome to Rick Case Honda!\n\n"
                "💬 Ask me any Honda questions or type 'book appointment' to schedule service!\n\n"
                "💡 Tip: Mention your car model in your question (Civic, Passport, or Ridgeline)"
            )
            return
        else:
            await update.message.reply_text("🔒 Access Denied. Please send the shop password.")
            return
    
    # 2. CHECK FOR APPOINTMENT INTENT
    appointment_intent = detect_appointment_intent(user_text)
    if "YES" in appointment_intent:
        # Start appointment conversation
        return await start_appointment(update, context)
    
    # 3. GUARD - Check for escalation
    is_escalation = check_for_escalation(user_text)
    if "YES" in is_escalation:
        await update.message.reply_text(
            "I understand. I have flagged this for a service advisor. "
            "Someone will reach out shortly. Is there anything else I can help with?"
        )
        return
    
    # 4. ROUTER - Identify vehicle
    detected_car = identify_vehicle(user_text)
    target_car = None
    
    print(f"🔍 Detected vehicle: {detected_car}")
    
    # CRITICAL FIX: Check if this is a vehicle selection response
    # If user just says "Civic", "Passport", or "Ridgeline" by itself
    user_lower = user_text.strip().lower()
    if user_lower in ["civic", "passport", "ridgeline"]:
        # This is a vehicle selection, not a question
        if user_lower == "civic":
            target_car = "civic-2025"
        elif user_lower == "passport":
            target_car = "passport-2026"
        elif user_lower == "ridgeline":
            target_car = "ridgeline-2025"
        
        # Save to session
        user_sessions[user_id] = target_car
        
        await update.message.reply_text(
            f"✅ Got it! I'll help you with your {user_lower.title()}.\n\n"
            "What would you like to know?"
        )
        return
    
    # Otherwise, try to detect vehicle from the question
    if "unknown" not in detected_car:
        target_car = detected_car
        user_sessions[user_id] = target_car
        print(f"✅ Saved vehicle to session: {target_car}")
    elif user_id in user_sessions:
        target_car = user_sessions[user_id]
        print(f"📝 Using saved vehicle from session: {target_car}")
    
    # 5. RAG - Get answer from manual
    if target_car:
        print(f"🔎 Searching manual for: {user_text}")
        ai_answer = get_answer_from_manual(user_text, target_car)
        if "NO_ANSWER_FOUND" in ai_answer:
            await update.message.reply_text(
                "I checked the manual, but I couldn't find that specific detail. "
                "Would you like to schedule an appointment to speak with a technician?"
            )
        else:
            # Add helpful context about which vehicle we're talking about
            vehicle_name = target_car.replace("-", " ").title()
            await update.message.reply_text(
                f"📖 {vehicle_name} Manual:\n\n{ai_answer}\n\n"
                "Need anything else about this vehicle?"
            )
    else:
        # Ask for vehicle selection
        await update.message.reply_text(
            "I can help! Which vehicle is this for?\n"
            "• Passport\n"
            "• Civic\n"
            "• Ridgeline\n\n"
            "Just reply with the model name."
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles errors"""
    print(f"❌ Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Sorry, I encountered an error. Please try again or contact service directly."
        )

def main():
    """Start the bot"""
    # Get token from environment
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not found in .env file!")
        print("💡 Create a .env file with your Telegram bot token")
        return
    
    # Create application
    app = Application.builder().token(token).build()
    
    # Add appointment booking conversation handler
    appointment_handler = ConversationHandler(
        entry_points=[],  # No entry point - we trigger it manually
        states={
            CONFIRM_IDENTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_identity)],
            ASKING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            ASKING_VEHICLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_vehicle)],
            ASKING_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_service)],
            ASKING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            ASKING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel_appointment)],
        per_user=True,
        per_chat=True,
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_appointment))
    app.add_handler(appointment_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    # Start the bot
    print("\n" + "="*50)
    print("🤖 RICK CASE HONDA AI BOT")
    print("="*50)
    print(f"✅ Bot is running...")
    print(f"📊 Customer database: {len(customer_db.df)} records loaded")
    print(f"👥 Unique customers: {customer_db.df['PHONE'].nunique() if len(customer_db.df) > 0 else 0}")
    print(f"📅 Smart appointment scheduling: ENABLED")
    print(f"🔄 Returning customer detection: ENABLED")
    if ADVISOR_TELEGRAM_ID:
        print(f"📧 Advisor notifications: ENABLED (ID: {ADVISOR_TELEGRAM_ID})")
    else:
        print(f"⚠️  Advisor notifications: DISABLED (set ADVISOR_TELEGRAM_ID in .env)")
    print("\nPress Ctrl+C to stop")
    print("="*50 + "\n")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
