# Master Pro Dev AI Agent - 2 Tools Version

A scalable MCP (Model Context Protocol) based AI agent system with FastAPI, featuring Google Calendar and Gmail integration.

## 🎯 Features

- **MCP Host**: FastAPI-based central orchestrator
- **2 MCP Servers**: Calendar (port 8001) and Gmail (port 8002)
- **Authentication**: JWT + Bcrypt password hashing
- **State Management**: Redis caching + PostgreSQL persistence
- **Docker Support**: Complete docker-compose setup
- **Tests**: Unit and integration tests included

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- PostgreSQL client tools (optional)

### Setup

1. **Clone and install dependencies:**
```bash
cd C:\AI_Agent_MCP
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
copy .env.example .env
# Edit .env with your settings
```

3. **Start services:**
```bash
cd docker
docker-compose up -d
```

4. **Run MCP Host:**
```bash
python -m mcp_host.main
```

Visit: `http://localhost:8000/docs` for API documentation

## 📁 Structure

```
mcp_host/                 # Main FastAPI application
├── main.py              # Server with 6 endpoints
├── config.py            # Configuration management
├── models.py            # Pydantic request/response models
├── auth.py              # JWT + Bcrypt authentication
├── state.py             # State management (Redis/PostgreSQL)
└── __init__.py

mcp_servers/             # MCP Server implementations
├── base_server.py       # Base MCP server class
├── calendar_server/     # Calendar MCP server (port 8001)
└── gmail_server/        # Gmail MCP server (port 8002)

docker/                  # Docker infrastructure
├── docker-compose.yml   # 4 services: mcp-host, calendar, gmail, postgres, redis
├── Dockerfile.mcp_host
├── Dockerfile.mcp_servers
└── init-scripts/
    └── postgres/
        └── 01-schema.sql

tests/                   # Testing suite
├── unit/               # Unit tests
├── integration/        # Integration tests
└── conftest.py         # Pytest configuration
```

## 🧰 Tech Stack

**Languages & Frameworks:** Python, FastAPI, LangChain, LlamaIndex  
**Cloud:** AWS (EC2, S3, Bedrock, CloudWatch)  
**Vector Database:** Pinecone (AWS region)  
**Containerization:** Docker  
**CI/CD:** GitHub Actions  
**Monitoring:** CloudWatch, Grafana  
**Integrations:** Shopify API, Google Calendar API, Vendor Scraper

---

## 🗂 Vector Database Configuration

| Namespace | Purpose |
|------------|----------|
| `rag_kb` | Stores embeddings for RAGCHATBOT contextual retrieval |
| `vendor_ingestion` | Holds vendor product data from scraper pipelines |
| `mcp_context` | Maintains orchestration metadata and tool response logs |

Stored and backed up to **AWS S3**, ensuring persistence and recovery.

---

## 🚀 Deployment (AWS Free Tier Compatible)

1. **Launch EC2 Instance**  
   - Ubuntu 22.04 (t2.micro)  
   - Open ports 22 & 8000  

2. **Install Essentials**  
   ```bash
   sudo apt update && sudo apt install -y python3-pip docker.io git
   ```

3. **Run Containers**

   ```bash
   docker build -t mcpagent .
   docker run -d -p 8000:8000 mcpagent
   ```

4. **Access API**

   ```
   http://<ec2-public-ip>:8000
   ```

---

## 🧩 Key Functionalities

* **Single-Agent MCP Orchestration** – One MCP host managing multiple tool calls.
* **RAGCHATBOT Integration** – AWS Bedrock generation powered by Pinecone retrieval.
* **Vendor Data Pipeline** – Automated scraping, cleaning, and indexing.
* **Appointment Management** – Integration with Google Calendar for scheduling.
* **Product Automation** – Seamless Shopify updates via APIs.
* **Monitoring & CI/CD** – GitHub Actions for deployment, CloudWatch for logs.

---

## 🔒 Security & Observability

* Role-based IAM permissions for Bedrock, Pinecone, and API keys.
* Real-time orchestration monitoring with Grafana dashboards.
* Unified observability of all MCP tool calls and responses.
* Logging of all retriever and generator interactions for compliance.

---

## 🧭 Future Roadmap

* Integration with AWS Lambda for serverless retraining.
* Expansion to hybrid-cloud setup (Azure AI + AWS Bedrock).
* RAGCHATBOT fine-tuning using company-specific corpora.
* Enhanced context tracing through OpenTelemetry instrumentation.

---

## 📂 Repository Layout

```
├── mcp_host/             # Main FastAPI host & orchestration logic
├── ragchatbot/           # RAG module (Retriever + Generator)
├── vendor_scraper/       # Web scraping scripts
├── integrations/         # Shopify & Google Calendar tools
├── vector_db/            # Pinecone namespace scripts
├── docker/               # Dockerfiles for each service
├── .github/workflows/    # CI/CD pipeline
└── README.md
```

---

## Architecture Diagram

![MCPAgent Architecture](docs/diagram.svg)

For the Mermaid source and an ASCII variant, see `docs/architecture_diagram.md` and `docs/diagram.mmd`.

---

## 🧑‍💻 Author’s Note

This project showcases how a **single MCP-driven agent** can orchestrate complex multi-tool automation — blending **RAG intelligence**, **retrieval workflows**, and **action pipelines** under a unified, containerized architecture.
The design demonstrates **real-world production readiness** through AWS Bedrock, Pinecone integration, and enterprise observability.

> “MCPAgent doesn’t just retrieve and respond — it *acts, coordinates, and scales intelligently*.”
> — **Srivardhan Muthyala**

---

If you want, I can now:
- Add badges and CI status to the top of the README.
- Add a short Getting Started script and sample env file.
- Add a sequence diagram for a use case (appointment booking or vendor ingestion).

Which should I do next?