import sys
import os
import json
import logging

# Configure logging to avoid spam
logging.basicConfig(level=logging.WARN)

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

try:
    from runtime.stores.redis_client import get_redis_client
    from runtime.stores.session_storage import SessionStorage
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

def main():
    try:
        client = get_redis_client()
        # Verify connection
        if not client.ping():
            print("Could not connect to Redis.")
            return

        storage = SessionStorage(client)
        
        # List all sessions
        print("Fetching sessions from 'sessions:all' index...")
        sessions, total = storage.get_all_sessions(page=1, page_size=5)
        
        print(f"Total sessions indexed: {total}")
        
        target_session_id = None

        if sessions:
            for s in sessions:
                print(f"ID: {s.id}, Title: {s.title}, Status: {s.status}, Updated: {s.updated_at}")
            target_session_id = sessions[0].id
        else:
            print("No sessions found via index. Scanning keys...")
            keys = client.keys("session:*:meta")
            print(f"Found {len(keys)} meta keys.")
            if keys:
                # Extract ID from "session:<id>:meta"
                # keys return without prefix from RedisClient.keys()
                # format: session:UUID:meta
                target_session_id = keys[0].split(":")[1]
                print(f"Using found key: {keys[0]} -> ID: {target_session_id}")

        if target_session_id:
            print(f"\nAnalyzing session: {target_session_id}")
            
            # Get raw raw list to see everything including potential weirdness
            # But SessionStorage.get_session_messages handles parsing
            messages = storage.get_session_messages(target_session_id)
            print(f"Total messages: {len(messages)}")
            
            for i, msg in enumerate(messages):
                content = msg.content or ""
                content_preview = content[:50].replace("\n", "\\n")
                print(f"[{i}] {msg.role} ({msg.id}): {content_preview}...")
                
                # Check for duplicate markers or specific strings
                if "Phase 3" in content or "Now completing" in content:
                    print(f"    MATCH: Found target string in message {i}")
                    print(f"    Full content len: {len(content)}")
                    print(f"    -- START --\n{content}\n    -- END --")
                
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
