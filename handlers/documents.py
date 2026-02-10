"""
Document Handlers — Advisor Carfax PDF uploads and ingestion.
"""

import os
from telegram import Update
from telegram.ext import ContextTypes

from config import ADVISOR_TELEGRAM_ID
from services.session import extract_vin, refresh_session_carfax
from services.customer_db import get_vehicle_by_vin, ingest_carfax


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle document uploads. If it's a PDF from the advisor with a VIN caption,
    ingest it as a Carfax report.
    """
    user_id = update.effective_user.id
    document = update.message.document

    # Only process PDFs
    if not document.file_name.lower().endswith(".pdf"):
        if ADVISOR_TELEGRAM_ID and user_id == ADVISOR_TELEGRAM_ID:
            await update.message.reply_text("I can only process PDF files. Please send the Carfax as a PDF.")
        return

    # Check if this is from the advisor
    if not ADVISOR_TELEGRAM_ID or user_id != ADVISOR_TELEGRAM_ID:
        await update.message.reply_text(
            "Thanks for the file! Right now I can only process documents sent by the service advisor. "
            "If you need help, just ask me a question about your vehicle."
        )
        return

    # Extract VIN from caption or filename
    caption = update.message.caption or ""
    vin = extract_vin(caption) or extract_vin(document.file_name)

    if not vin:
        await update.message.reply_text(
            "I need the VIN to know which vehicle this goes with.\n\n"
            "Please resend the PDF with the 17-digit VIN in the caption, like:\n"
            "2HGFE1E57TH472154"
        )
        return

    # Check if vehicle exists in DB
    vehicle = get_vehicle_by_vin(vin)
    if not vehicle:
        await update.message.reply_text(
            f"⚠️ No vehicle found for VIN: {vin}\n"
            f"The customer needs to register first by sending their phone number and VIN to the bot."
        )
        return

    await update.message.reply_text(f"📥 Got it — ingesting Carfax for VIN: {vin[:8]}... This will take a minute.")

    # Download the PDF
    os.makedirs("./data/carfax", exist_ok=True)
    pdf_path = f"./data/carfax/carfax_{vin}.pdf"

    try:
        file = await document.get_file()
        await file.download_to_drive(pdf_path)
        print(f"   📥 Downloaded Carfax PDF: {pdf_path}")
    except Exception as e:
        print(f"   ❌ PDF download failed: {e}")
        await update.message.reply_text(f"❌ Failed to download the PDF: {e}")
        return

    # Ingest into Pinecone
    try:
        success = ingest_carfax(pdf_path, vin)

        if success:
            await update.message.reply_text(
                f"✅ Carfax ingested for VIN: {vin}\n\n"
                f"Vehicle: {vehicle['year']} {vehicle['make']} {vehicle['model']}\n"
                f"Namespace: carfax-{vin}\n\n"
                f"The customer can now ask about their vehicle history, "
                f"warranty status, accidents, and more."
            )
            # Update live session if customer is online
            refresh_session_carfax(vin)
        else:
            await update.message.reply_text(f"❌ Ingestion failed for VIN: {vin}. Check the logs.")

    except Exception as e:
        print(f"   ❌ Carfax ingestion error: {e}")
        await update.message.reply_text(f"❌ Error during ingestion: {e}")
