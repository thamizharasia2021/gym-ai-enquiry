# Tarvos Fit — Gym AI Enquiry Assistant & Admin Hub 🏋️‍♂️

A production-ready, highly secure RAG-powered chatbot and web platform for **tarvos.fit** (and multi-gym deployments). It features a central **Admin Portal**, a **Button-First Web Chat** greeted with the gym name, **WhatsApp Bot Integration**, strict **No-PII-to-LLM Security**, a **Website Generator** with Instagram, Google Maps & Google Reviews, and **Zero-Friction Render Deployment**.

---

## 🌟 Key Features

1. **Executive Admin Command Hub (`/admin`)**:
   - Central control for knowledge base configuration, website generation, live chat preview, WhatsApp bot mapping, and real-time lead analytics.
2. **Button-First Visitor Chat (`/chat`)**:
   - Greeted dynamically with the gym name (e.g. *“Hi! Welcome to Tarvos Fit!”*).
   - Structured quick-action category buttons (Plans, Timings, PT, Free Trial, Facilities, Location, Reviews) so users rarely need to type open-ended questions.
   - Interactive 3-step qualification quiz (*"Find My Plan"*).
3. **Strict No-PII-to-LLM Privacy & Cost Protection**:
   - Visitor lead data (Name, Phone number, Email, Preferred Timing) is **NEVER** sent to Gemini or external LLMs.
   - Lead capture is executed directly through deterministic backend code (`POST /api/gym/{gym_id}/leads`).
   - In-chat phone detection intercepts contact numbers in code and returns instant confirmation without consuming LLM tokens.
4. **Low-Cost Gemini Model**:
   - Configured with `gemini-2.0-flash` (ultra-low cost, fast, stable) and `gemini-embedding-001`.
5. **High-Converting Website Generator**:
   - Generates a website for `tarvos.fit` featuring **Instagram Feed / Reels showcase**, **Interactive Google Maps Embed**, **Google Reviews Widget (4.9 ★)**, **1-Day Free Pass Lead Form**, and **Embedded Web Chat**.
6. **Meta WhatsApp Cloud API Bot**:
   - Webhook at `/webhook/whatsapp` connects directly to the same RAG knowledge base.
7. **Production Security**:
   - Sliding-window rate limiting per client IP (30 chat/min, 10 leads/min).
   - Security headers (`X-Content-Type-Options`, `X-XSS-Protection`, `SAMEORIGIN` frames).
   - PDF upload validation (magic bytes `%PDF-`, MIME check, 10MB limit).

---

## 🗺️ System Architecture & Routes

When running locally or on Render, all pages and APIs are served seamlessly from a single service:

| Route | Page / Function | Description |
| :--- | :--- | :--- |
| `/` or `/admin` | **Admin Command Hub** | Master dashboard, stats, quick launches, live leads feed |
| `/setup` | **Setup Wizard & PDF Ingest** | Upload knowledge PDF, edit 137 canonical Q&As, generate website |
| `/chat` | **Button-First Web Chat** | Standalone visitor chat with dynamic gym greeting |
| `/dashboard` | **Owner CRM Pipeline** | Track lead stages, send WhatsApp messages, view insights |
| `/webhook/whatsapp` | **WhatsApp Webhook** | Meta Cloud API incoming message webhook |
| `/api/system/config` | **System Config API** | Domain (`tarvos.fit`), chat subdomain, model info |
| `/health` | **Health Check** | Service status and vector backend verification |

---

## 🚀 Deploying to Render

This repository includes a pre-configured `render.yaml` Blueprint for 1-click deployment.

### Steps to Deploy on Render:
1. Push this repository to your GitHub account.
2. Log into [Render Dashboard](https://dashboard.render.com/) and click **New +** → **Blueprint**.
3. Select your repository. Render will automatically detect `render.yaml`.
4. In the Environment Variables settings, set your `GEMINI_API_KEY`:
   - `GEMINI_API_KEY`: Get a free key from [Google AI Studio](https://aistudio.google.com/apikey).
   - `APP_DOMAIN`: `tarvos.fit` (or your custom domain).
   - `CHAT_SUBDOMAIN`: `chat.tarvos.fit`.
   - `GEMINI_CHAT_MODEL`: `gemini-2.0-flash`.
   - `ADMIN_KEY`: Your secret passcode for admin actions.
5. Click **Apply**. Render will build and deploy your service.
6. Once deployed, attach your custom domain `tarvos.fit` in Render’s **Custom Domains** tab.

---

## 💻 Local Development Setup

### 1. Backend & Server
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # Add your GEMINI_API_KEY in .env

# Run FastAPI server
uvicorn backend.app.main:app --reload --port 8000
```

### 2. Access the Application
Open your browser to:
- **Admin Hub**: `http://localhost:8000/admin`
- **Setup & PDF Upload Wizard**: `http://localhost:8000/setup`
- **Web Chat**: `http://localhost:8000/chat`
- **CRM Dashboard**: `http://localhost:8000/dashboard`

---

## 📱 WhatsApp Cloud API Integration

1. Create a Meta Developer app → Add the **WhatsApp** product ([Getting Started Guide](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)).
2. Set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, and `WHATSAPP_VERIFY_TOKEN` in your `.env` or Render environment.
3. Configure the Webhook in Meta developer dashboard to point at:
   `https://tarvos.fit/webhook/whatsapp` (or your Render service URL).
4. Webhook verification challenge will succeed automatically using `WHATSAPP_VERIFY_TOKEN`.
5. Incoming WhatsApp messages will be answered using the same approved RAG knowledge base.

