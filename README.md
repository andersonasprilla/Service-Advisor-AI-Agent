# Rick Case Honda AI Service Agent

An AI-powered Telegram bot that handles the busywork of being a service advisor — answering customer questions from the owner's manual, booking appointments through natural conversation, and recognizing returning customers automatically.

## The Problem

Service advisors spend hours every day answering the same questions ("How do I reset my tire pressure light?"), collecting the same info for appointments ("Name? Phone? Vehicle? Date? Time?"), and manually looking up customer history. It's repetitive, time-consuming, and pulls you away from the work that actually needs a human.

## What This Bot Does

**Answers vehicle questions instantly** — Customers text a question about their Honda (Civic, Ridgeline, or Passport), and the bot pulls the answer straight from the owner's manual using AI-powered search. No hallucinations — every answer is grounded in actual manual content.

**Books appointments through natural conversation** — No rigid forms. A customer can say "I need an oil change for my Civic tomorrow morning" and the bot extracts everything in one shot. It asks for whatever's missing, confirms, and sends a formatted notification to the advisor's phone.

**Recognizes returning customers** — When a customer gives their phone number, the bot pulls up their name, vehicle history, past services, and visit count. It greets them by name and pre-fills their info so booking takes seconds instead of minutes.

**Speaks the customer's language** — Auto-detects English, Spanish, Portuguese, French, Haitian Creole, and more. Responds naturally in whatever language the customer texts in — critical for South Florida.

**Knows when to escalate** — Detects frustrated customers or requests for a real person and flags the conversation for immediate advisor attention.

## Why This Works

**For customers**: They get instant answers 24/7 without waiting on hold or driving to the dealership. Booking feels like texting a friend, not filling out a form.

**For advisors**: Every appointment lands in your Telegram as a clean, formatted notification ready to plug into CDK/DMS. Returning customer history is right there — no digging through systems.

**For the dealership**: More appointments booked, faster response times, happier customers, and advisors freed up to focus on in-person service.

## Tech Stack

- **Telegram Bot** for the customer-facing interface
- **OpenAI GPT-4o-mini** for conversation and intent routing
- **Pinecone** vector database for owner's manual search (RAG)
- **SQLite** for customer profiles and vehicle records (with VIN decoding)
- **Python** with LangChain orchestration

## Status

**Version 1.0** — Live and functional. Built by a working service advisor to solve real problems on the drive.

---

*Rick Case Honda — Internal Use*
