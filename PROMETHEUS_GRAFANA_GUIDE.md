# Prometheus & Grafana Integration Guide

## Overview

The AI Agent now exports comprehensive evaluation metrics to Prometheus, allowing real-time monitoring in Grafana dashboards.

## Metrics Exported

### Task Counters
- **`agent_tasks_total{category, status}`** - Total tasks by category and outcome
  - Labels: `category` (calendar/knowledge/email/conversation), `status` (success/failure)
  - Type: Counter
  - Example: `agent_tasks_total{category="calendar", status="success"}`

### Success Rate Gauges
- **`agent_calendar_success_rate`** - Calendar task success rate (0-100%)
- **`agent_knowledge_success_rate`** - Knowledge base task success rate (0-100%)
- **`agent_email_success_rate`** - Email task success rate (0-100%)
- **`agent_conversation_success_rate`** - Conversation task success rate (0-100%)
- **`agent_overall_success_rate`** - Overall success rate (0-100%)
- **`agent_production_ready`** - Production readiness (1=ready, 0=not ready)

### Performance Metrics
- **`agent_task_duration_seconds{category}`** - Task processing time histogram
  - Labels: `category`
  - Buckets: Auto-generated (0.5s, 1s, 2s, 5s, 10s, 30s, 60s)

## Accessing Metrics

### 1. Prometheus Metrics Endpoint
```
GET https://your-railway-app.up.railway.app/metrics
```

**Output:**
```prometheus
# HELP agent_tasks_total Total number of tasks processed by category
# TYPE agent_tasks_total counter
agent_tasks_total{category="calendar",status="success"} 15.0
agent_tasks_total{category="calendar",status="failure"} 2.0
agent_tasks_total{category="knowledge",status="success"} 23.0

# HELP agent_overall_success_rate Overall task success rate (0-100)
# TYPE agent_overall_success_rate gauge
agent_overall_success_rate 88.5

# HELP agent_production_ready Production readiness status (1=ready, 0=not ready)
# TYPE agent_production_ready gauge
agent_production_ready 1.0
```

### 2. REST API Endpoint (Detailed)
```
GET https://your-railway-app.up.railway.app/evaluation
Authorization: Bearer <your-token>
```

Returns JSON with detailed task results and metrics.

## Railway Deployment Setup

### Environment Variables (Already set)
No additional env vars needed - metrics are auto-exported.

### Testing Locally

**1. Start the application:**
```bash
python -m uvicorn mcp_host.main:app --reload
```

**2. Generate some tasks:**
- Chat: "Tell me about Master Pro Dev"
- Calendar: "What's on my schedule?"
- Conversation: "Hello"

**3. Check metrics:**
```bash
curl http://localhost:8000/metrics | grep agent_
```

**Output:**
```
agent_tasks_total{category="knowledge",status="success"} 1.0
agent_knowledge_success_rate 100.0
agent_overall_success_rate 100.0
agent_production_ready 1.0
```

## Grafana Dashboard Setup

### Option 1: Import Pre-built Dashboard

1. **Access Grafana** (if you have it deployed)
   - Railway: Add Grafana service
   - Or use Grafana Cloud (free tier)

2. **Import Dashboard:**
   - Go to Dashboards → Import
   - Upload `grafana-dashboard.json`
   - Select Prometheus data source
   - Click Import

3. **View Metrics:**
   - Overall Success Rate (Gauge)
   - Production Ready Status
   - Success by Category (Bar Chart)
   - Task Completion Over Time
   - Task Distribution (Pie Chart)
   - Processing Duration (P95/P50)

### Option 2: Manual Setup

**Add Prometheus Data Source:**
1. Grafana → Configuration → Data Sources
2. Add Prometheus
3. URL: `https://your-railway-app.up.railway.app`
4. Save & Test

**Create Panels:**

**Panel 1: Overall Success Rate**
```promql
agent_overall_success_rate
```

**Panel 2: Tasks per Minute (Success)**
```promql
rate(agent_tasks_total{status="success"}[5m])
```

**Panel 3: Production Ready**
```promql
agent_production_ready
```

**Panel 4: Success Rate by Category**
```promql
agent_calendar_success_rate
agent_knowledge_success_rate
agent_email_success_rate
agent_conversation_success_rate
```

## Railway Grafana Integration

### Deploy Grafana on Railway

**1. Add Grafana Service:**
```bash
# In Railway dashboard
+ New → Database → Add Grafana
```

**2. Configure:**
- Set admin password in env vars
- Connect to Prometheus (your main app URL)

**3. Access:**
```
https://your-grafana-service.railway.app
Login: admin / <your-password>
```

**4. Add Prometheus Data Source:**
- URL: `https://masterprodevmcpaiagent-production.up.railway.app`
- Access: Server (default)

**5. Import Dashboard:**
- Upload `grafana-dashboard.json`
- Done!

## Metrics Update Frequency

- **Real-time:** Metrics update immediately after each task
- **Prometheus scrape:** Every 15s (default)
- **Grafana refresh:** Configurable (default: 5s)

## Production Monitoring Alerts

### Example Alert Rules

**Alert: Production Not Ready**
```promql
agent_production_ready < 1
```

**Alert: High Failure Rate**
```promql
rate(agent_tasks_total{status="failure"}[5m]) > 0.1
```

**Alert: Calendar Success Below Threshold**
```promql
agent_calendar_success_rate < 90
```

## Troubleshooting

**Metrics not appearing?**
1. Check `/metrics` endpoint returns data
2. Verify Prometheus can reach your Railway app
3. Check Grafana data source connection
4. Run some tasks to generate metrics

**Old metrics showing?**
- Metrics are cumulative (counters never decrease)
- Use `rate()` function for per-minute calculations
- Gauges update in real-time

**Need historical data?**
- Add Prometheus server (Railway template available)
- Configure scraping from your app's `/metrics`
- Set retention period (default: 15 days)

## Next Steps

1. ✅ Metrics exported (done)
2. ⏳ Deploy Grafana on Railway
3. ⏳ Import dashboard JSON
4. ⏳ Set up alerts
5. ⏳ Monitor production readiness

## Dashboard Preview

Once imported, you'll see:
- 📊 Real-time success rates
- 📈 Task trends over time
- 🎯 Production readiness indicator
- ⚡ Performance metrics (P95 latency)
- 🔍 Category breakdowns
