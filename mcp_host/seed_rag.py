import asyncio
from mcp_host.rag_service import rag_service

TOOL_DOCS = [
    {
        "text": "The 'create_calendar_event' tool schedules a new event in Google Calendar. It requires a 'summary' (the event title), a 'start_time', and an 'end_time'. Times must be in ISO 8601 format (e.g., '2025-12-22T14:00:00').",
        "source": "mcp_tools.py",
        "category": "tool_docs"
    },
    {
        "text": "The 'get_calendar_events' tool retrieves a list of upcoming events from Google Calendar. It takes an optional 'max_results' parameter to limit the number of events returned.",
        "source": "mcp_tools.py",
        "category": "tool_docs"
    },
    {
        "text": "The 'send_email' tool sends an email using Gmail. It requires a 'recipient', a 'subject', and a 'body'.",
        "source": "mcp_tools.py",
        "category": "tool_docs"
    },
    {
        "text": "The 'get_emails' tool fetches the most recent emails from the user's Gmail inbox. It can be filtered by 'sender' or 'subject'.",
        "source": "mcp_tools.py",
        "category": "tool_docs"
    }
]

BUSINESS_POLICIES = [
    {
        "text": "Standard business hours for scheduling meetings are Monday to Friday, from 9:00 AM to 5:00 PM Pacific Time.",
        "source": "Company Policy Manual",
        "category": "policies"
    },
    {
        "text": "Meetings cannot be scheduled on company holidays. The next upcoming holiday is New Year's Day.",
        "source": "Company Policy Manual",
        "category": "policies"
    }
]

async def main():
    print("Initializing RAG service...")
    rag_service.initialize()
    
    if rag_service.client:
        print("Seeding tool documentation...")
        rag_service.index_documents(TOOL_DOCS)
        
        print("Seeding business policies...")
        rag_service.index_documents(BUSINESS_POLICIES)
        
        print("Seeding complete.")
        
        # Verify seeding
        print("\nVerifying tool docs seeding...")
        results = rag_service.search("how to send an email", category="tool_docs")
        for r in results:
            print(f"- {r['text']} (Source: {r['source']})")

        print("\nVerifying policy seeding...")
        results = rag_service.search("what are the meeting hours", category="policies")
        for r in results:
            print(f"- {r['text']} (Source: {r['source']})")

if __name__ == "__main__":
    asyncio.run(main())
