#!/usr/bin/env python3
"""
Test ACME endpoint availability
Usage: python scripts/test_acme_endpoint.py medcard.ryabich.co
"""
import sys
import asyncio
import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.redis import redis_client
from app.core.config import settings

async def test_acme_endpoint(fqdn: str):
    """Test if ACME challenge endpoint is accessible"""
    
    print("=" * 80)
    print(f"Testing ACME endpoint for: {fqdn}")
    print("=" * 80)
    
    # Connect to Redis
    print("\n[1/5] Connecting to Redis...")
    await redis_client.connect()
    print(f"✓ Connected to Redis")
    
    # Store test token
    test_token = "TEST_TOKEN_123456789"
    test_validation = "TEST_VALIDATION_RESPONSE_987654321"
    
    print(f"\n[2/5] Storing test token in Redis...")
    await redis_client.set(f"acme:challenge:{test_token}", test_validation, expire=300)
    print(f"✓ Stored: acme:challenge:{test_token}")
    
    # Verify storage
    retrieved = await redis_client.get(f"acme:challenge:{test_token}")
    if retrieved == test_validation:
        print(f"✓ Verified: Can retrieve from Redis")
    else:
        print(f"✗ ERROR: Redis retrieval failed!")
        return False
    
    # Test local endpoint
    print(f"\n[3/5] Testing local endpoint (http://localhost:{settings.PORT})...")
    test_url = f"http://localhost:{settings.PORT}/.well-known/acme-challenge/{test_token}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(test_url, timeout=5.0)
            
            if response.status_code == 200:
                print(f"✓ Status: {response.status_code}")
                print(f"✓ Response: {response.text[:100]}")
                
                if response.text == test_validation:
                    print(f"✓✓✓ LOCAL ENDPOINT WORKS PERFECTLY!")
                else:
                    print(f"✗ Response mismatch!")
                    print(f"  Expected: {test_validation}")
                    print(f"  Got: {response.text}")
                    return False
            else:
                print(f"✗ ERROR: Status {response.status_code}")
                print(f"  Response: {response.text[:200]}")
                return False
    except Exception as e:
        print(f"✗ ERROR: {e}")
        print(f"\n💡 SOLUTION: Restart the application:")
        print(f"   systemctl restart cdn_waf")
        return False
    
    # Test public endpoint
    print(f"\n[4/5] Testing public endpoint (http://{fqdn})...")
    public_url = f"http://{fqdn}/.well-known/acme-challenge/{test_token}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(public_url, timeout=10.0, follow_redirects=True)
            
            if response.status_code == 200:
                print(f"✓ Status: {response.status_code}")
                print(f"✓ Response: {response.text[:100]}")
                
                if response.text == test_validation:
                    print(f"✓✓✓ PUBLIC ENDPOINT WORKS!")
                    print(f"✓✓✓ LET'S ENCRYPT WILL BE ABLE TO VALIDATE!")
                else:
                    print(f"✗ Response mismatch!")
                    print(f"  Expected: {test_validation}")
                    print(f"  Got: {response.text[:100]}")
                    return False
            else:
                print(f"✗ ERROR: Status {response.status_code}")
                print(f"  Response: {response.text[:200]}")
                
                if response.status_code == 404:
                    print(f"\n💡 POSSIBLE CAUSES:")
                    print(f"   1. DNS not pointing to correct server")
                    print(f"   2. Nginx not configured to proxy ACME requests")
                    print(f"   3. Application not running or endpoint not registered")
                
                return False
    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False
    
    # Simulate Let's Encrypt
    print(f"\n[5/5] Simulating Let's Encrypt validation...")
    print(f"  Let's Encrypt will:")
    print(f"  1. Make HTTP GET request to: {public_url}")
    print(f"  2. Expect to receive: {test_validation}")
    print(f"  3. Compare with computed validation from your account key")
    print(f"\n✓✓✓ ALL CHECKS PASSED!")
    print(f"✓✓✓ SAFE TO PROCEED WITH REAL CERTIFICATE ISSUANCE!")
    
    # Cleanup
    await redis_client.delete(f"acme:challenge:{test_token}")
    await redis_client.disconnect()
    
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_acme_endpoint.py <fqdn>")
        print("Example: python scripts/test_acme_endpoint.py medcard.ryabich.co")
        sys.exit(1)
    
    fqdn = sys.argv[1]
    result = asyncio.run(test_acme_endpoint(fqdn))
    
    if result:
        print("\n" + "=" * 80)
        print("✓ Ready to issue certificate!")
        print("  Run: python scripts/issue_certificate.py", fqdn)
        print("=" * 80)
        sys.exit(0)
    else:
        print("\n" + "=" * 80)
        print("✗ Endpoint not ready! Fix issues above before proceeding.")
        print("=" * 80)
        sys.exit(1)

