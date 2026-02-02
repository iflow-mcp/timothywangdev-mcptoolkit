#!/usr/bin/env python3
"""
Simple direct test for MCP server
"""
import sys
import subprocess
import json
import os
import time

def test_mcp_server():
    """Test MCP server functionality"""
    print("Starting MCP server test...")
    
    # Start the server process
    proc = subprocess.Popen(
        ["/app/auto-mcp-upload/.venv/bin/python3", "/app/auto-mcp-upload/data/2714/main.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0
    )
    
    try:
        # Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }
        
        print(f"Sending initialize request...")
        proc.stdin.write(json.dumps(init_request) + "\n")
        proc.stdin.flush()
        
        # Read response with timeout
        import select
        start_time = time.time()
        response_line = ""
        
        while time.time() - start_time < 5:
            if select.select([proc.stdout], [], [], 0.1)[0]:
                char = proc.stdout.read(1)
                if char == "\n":
                    break
                response_line += char
                continue
        
        if not response_line:
            print("❌ No response from server")
            return False
        
        response = json.loads(response_line)
        print(f"✅ Initialize response received")
        
        # Send initialized notification
        initialized = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        proc.stdin.write(json.dumps(initialized) + "\n")
        proc.stdin.flush()
        
        # List tools
        list_tools_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }
        print(f"Sending tools/list request...")
        proc.stdin.write(json.dumps(list_tools_request) + "\n")
        proc.stdin.flush()
        
        # Read tools response
        start_time = time.time()
        tools_response_line = ""
        
        while time.time() - start_time < 5:
            if select.select([proc.stdout], [], [], 0.1)[0]:
                char = proc.stdout.read(1)
                if char == "\n":
                    break
                tools_response_line += char
                continue
        
        if not tools_response_line:
            print("❌ No tools response from server")
            return False
        
        tools_response = json.loads(tools_response_line)
        
        # Check if tools are available
        if "result" in tools_response and "tools" in tools_response["result"]:
            tools = tools_response["result"]["tools"]
            print(f"✅ Success! Found {len(tools)} tools:")
            for tool in tools:
                print(f"  - {tool['name']}: {tool.get('description', 'No description')}")
            return True
        else:
            print("❌ No tools found in response")
            print(f"Response: {json.dumps(tools_response, indent=2)}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        try:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=2)
        except:
            try:
                proc.kill()
            except:
                pass

if __name__ == "__main__":
    success = test_mcp_server()
    sys.exit(0 if success else 1)