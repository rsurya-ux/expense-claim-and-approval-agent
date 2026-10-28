# ExpenseOps Manager Dashboard & Approval Service

A standalone, dark glassmorphism Manager Dashboard and Human-in-the-Loop (HITL) approval gateway for the Ambient Expense Agent deployed on Google Cloud Vertex AI Agent Runtime.

---

## Architecture & Features

- **FastAPI Backend:**
  - `GET /`: Interactive glassmorphic manager dashboard with Outfit/Inter typography, radial glow accents, and responsive approval cards.
  - `GET /api/pending`: Connects to `VertexAiSessionService`, inspects active sessions, and filters unresolved `adk_request_input` interruption events.
  - `POST /api/action/{session_id}`: Resumes paused sessions on Vertex AI Agent Runtime with an approval (`approved: true`) or rejection (`approved: false`) payload under `user_id="default-user"`.
  - `POST /api/submit-expense`: Developer utility to submit test expenses directly to the reasoning engine from the UI.
  - `GET /api/config`: Exposes active GCP project and reasoning engine configuration.

- **Design & UI:**
  - **Sleek Glassmorphism:** Layered radial gradients, backdrop blur, dark slate palette (`#07090e`), subtle border highlights.
  - **Interactive Action Cards:** Amount formatted in currency, policy trigger details, employee metadata, and live action spinners.
  - **Slide-out Decision Modal:** Shows the agent's full markdown audit receipt upon approval/rejection.
  - **Auto-Refresh:** Live syncing of pending reviews every 8 seconds.

---

## Configuration

Set the environment variables (defaults match the project deployment):

```bash
export GOOGLE_CLOUD_PROJECT="surya-kaggle-day1b-project"
export GOOGLE_CLOUD_LOCATION="us-central1"
export AGENT_RUNTIME_ID="projects/304616680887/locations/us-central1/reasoningEngines/4814069000583512064"
export APP_NAME="app"
```

---

## Running the Service

### On Cloudtop (Recommended):
```bash
cd ~/submission_frontend
pip install -e .
uvicorn main:app --host 0.0.0.0 --port 8001
```

Access the dashboard at `http://localhost:8001`.
