#!/usr/bin/env python3
"""
Test MCP server using stdio protocol
"""
import asyncio
import sys
import subprocess
import json
import os

async def test_mcp_server():
    """Test MCP server functionality"""
    cmd = ["/app/auto-mcp-upload/.venv/bin/python3", "/app/auto-mcp-upload/data/2714/main.py"]
    
    # Start the server process
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
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
        
        # Write request
        proc.stdin.write((json.dumps(init_request) + "\n").encode())
        await proc.stdin.drain()
        
        # Read response
        response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        if not response_line:
            print("No response from server")
            return False
        
        response = json.loads(response_line.decode())
        print(f"Initialize response: {json.dumps(response, indent=2)}")
        
        # Send initialized notification
        initialized = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        proc.stdin.write((json.dumps(initialized) + "\n").encode())
        await proc.stdin.drain()
        
        # List tools
        list_tools_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }
        proc.stdin.write((json.dumps(list_tools_request) + "\n").encode())
        await proc.stdin.drain()
        
        # Read tools response
        tools_response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        if not tools_response_line:
            print("No tools response from server")
            return False
        
        tools_response = json.loads(tools_response_line.decode())
        print(f"\nTools list response: {json.dumps(tools_response, indent=2)}")
        
        # Check if tools are available
        if "result" in tools_response and "tools" in tools_response["result"]:
            tools = tools_response["result"]["tools"]
            print(f"\n✅ Success! Found {len(tools)} tools:")
            for tool in tools:
                print(f"  - {tool['name']}: {tool.get('description', 'No description')}")
            return True
        else:
            print("❌ No tools found in response")
            return False
            
    except asyncio.TimeoutError:
        print("❌ Timeout waiting for server response")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        # Cleanup
        try:
            proc.stdin.close()
            await proc.wait()
        except:
            pass

if __name__ == "__main__":
    success = asyncio.run(test_mcp_server())
    sys.exit(0 if success else 1)