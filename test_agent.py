"""Quick test script for MCP Agent"""

import asyncio
import logging
from mcp_host.agent import mcp_agent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_agent():
    """Test the agent with sample queries"""
    
    print("\n" + "="*70)
    print("🤖 MCP AGENT TEST SUITE")
    print("="*70 + "\n")
    
    # Initialize agent
    print("📌 Initializing agent...")
    await mcp_agent.initialize()
    
    # Get agent status
    status = mcp_agent.get_status()
    print(f"\n✓ Agent initialized successfully!")
    print(f"  • Tools loaded: {status['tools_count']}")
    print(f"  • Available tools: {', '.join(status['tools'])}")
    print(f"  • LLM provider: {status['llm_provider']}")
    
    # Test queries
    test_queries = [
        {
            "name": "Calendar Query",
            "message": "What meetings do I have in the next 3 days?",
            "expected_tool": "get_calendar_events"
        },
        {
            "name": "Email Query",
            "message": "Check my unread emails",
            "expected_tool": "get_emails"
        },
        {
            "name": "Create Event",
            "message": "Schedule a team meeting tomorrow at 2pm for 1 hour",
            "expected_tool": "create_calendar_event"
        },
        {
            "name": "Send Email",
            "message": "Send an email to john@company.com with subject 'Meeting Reminder' and body 'Don't forget our meeting tomorrow'",
            "expected_tool": "send_email"
        },
        {
            "name": "General Query (No Tools)",
            "message": "What's the weather like?",
            "expected_tool": None
        }
    ]
    
    print("\n" + "="*70)
    print("🧪 RUNNING TEST QUERIES")
    print("="*70 + "\n")
    
    for i, test in enumerate(test_queries, 1):
        print(f"\n{'─'*70}")
        print(f"Test {i}/{len(test_queries)}: {test['name']}")
        print(f"{'─'*70}")
        print(f"📝 Query: {test['message']}")
        print(f"🎯 Expected tool: {test['expected_tool'] or 'None (direct answer)'}")
        
        try:
            result = await mcp_agent.process_message(test['message'])
            
            print(f"\n✅ SUCCESS")
            print(f"⏱️  Execution time: {result['execution_time']:.2f}s")
            print(f"🤖 Response: {result['response'][:200]}...")
            
            if result.get('tool_calls'):
                print(f"🔧 Tools used: {len(result['tool_calls'])}")
                for j, tool_call in enumerate(result['tool_calls'], 1):
                    print(f"   {j}. {tool_call['tool']}")
            else:
                print(f"🔧 Tools used: None")
            
            print(f"💡 LLM Provider: {result.get('llm_provider', {}).get('provider', 'unknown')}")
            
        except Exception as e:
            print(f"\n❌ FAILED")
            print(f"Error: {str(e)}")
    
    print("\n" + "="*70)
    print("✅ TEST SUITE COMPLETED")
    print("="*70 + "\n")


async def interactive_mode():
    """Interactive chat mode for testing"""
    print("\n" + "="*70)
    print("💬 INTERACTIVE MODE - Type 'exit' to quit")
    print("="*70 + "\n")
    
    await mcp_agent.initialize()
    print("✓ Agent ready! Ask me anything...\n")
    
    conversation_history = []
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['exit', 'quit', 'q']:
                print("\n👋 Goodbye!")
                break
            
            if user_input.lower() == 'status':
                status = mcp_agent.get_status()
                print(f"\n📊 Agent Status:")
                print(f"  • Tools: {', '.join(status['tools'])}")
                print(f"  • LLM: {status['llm_provider']}")
                print()
                continue
            
            if user_input.lower() == 'tools':
                tools = await mcp_agent.get_available_tools()
                print(f"\n🔧 Available Tools:")
                for tool in tools:
                    print(f"  • {tool['name']}: {tool['description']}")
                print()
                continue
            
            # Process message
            result = await mcp_agent.process_message(
                message=user_input,
                conversation_history=conversation_history
            )
            
            # Add to history
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": result['response']})
            
            # Keep only last 10 messages
            if len(conversation_history) > 10:
                conversation_history = conversation_history[-10:]
            
            # Display response
            print(f"\nAgent: {result['response']}\n")
            
            if result.get('tool_calls'):
                print(f"[Used tools: {', '.join([tc['tool'] for tc in result['tool_calls']])}]")
                print(f"[Execution time: {result['execution_time']:.2f}s]\n")
        
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {str(e)}\n")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        asyncio.run(interactive_mode())
    else:
        asyncio.run(test_agent())
