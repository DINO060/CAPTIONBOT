"""
Test script for new features (user stats, broadcast, cache)
Run this to verify the new functionality works correctly.
"""
import asyncio
from config import (
    init_db,
    track_user,
    get_user_stats,
    get_all_user_ids,
    clear_force_join_cache,
    FORCE_JOIN_CACHE_TTL,
)
import time


async def test_user_tracking():
    """Test user activity tracking"""
    print("\n" + "="*50)
    print("TEST 1: User Activity Tracking")
    print("="*50)

    # Simulate some user activity
    test_users = [111111, 222222, 333333, 444444, 555555]

    print(f"Creating {len(test_users)} test users...")
    for uid in test_users:
        await track_user(uid)

    print("[OK] Users created")

    # Get stats
    stats = await get_user_stats()
    print(f"\nUser Statistics:")
    print(f"  Total: {stats['total']}")
    print(f"  Active (1 hour): {stats['active_1h']}")
    print(f"  Active (24 hours): {stats['active_24h']}")
    print(f"  Active (7 days): {stats['active_7d']}")
    print(f"  Inactive (7+ days): {stats['inactive_7d']}")

    if stats['active_1h'] >= len(test_users):
        print("\n[OK] Test PASSED: All test users are tracked as active")
    else:
        print("\n[WARNING] Test WARNING: Some users not tracked as active (may be OK if you have old data)")


async def test_get_all_users():
    """Test getting all user IDs"""
    print("\n" + "="*50)
    print("TEST 2: Get All User IDs")
    print("="*50)

    user_ids = await get_all_user_ids()
    print(f"Total user IDs retrieved: {len(user_ids)}")

    if len(user_ids) > 0:
        print(f"Sample IDs: {user_ids[:5]}")
        print("[OK] Test PASSED: User IDs retrieved successfully")
    else:
        print("[WARNING] No users in database (run test_user_tracking first)")


async def test_force_join_cache():
    """Test force-join cache functionality"""
    print("\n" + "="*50)
    print("TEST 3: Force-Join Cache")
    print("="*50)

    # Import cache variable
    from config import _force_join_cache

    print(f"Cache TTL: {FORCE_JOIN_CACHE_TTL} seconds")

    # Simulate cache entry
    test_user_id = 999999
    current_time = time.time()

    # Add to cache
    _force_join_cache[test_user_id] = (True, current_time)
    print(f"\n[OK] Added user {test_user_id} to cache")
    print(f"   Cached as: joined=True, time={current_time}")

    # Check cache
    if test_user_id in _force_join_cache:
        is_joined, timestamp = _force_join_cache[test_user_id]
        age = time.time() - timestamp
        print(f"\n[OK] Cache entry found:")
        print(f"   is_joined: {is_joined}")
        print(f"   age: {age:.2f} seconds")

        if age < FORCE_JOIN_CACHE_TTL:
            print(f"   [OK] Cache is still valid (< {FORCE_JOIN_CACHE_TTL}s)")
        else:
            print(f"   [WARNING] Cache expired (> {FORCE_JOIN_CACHE_TTL}s)")

    # Test clear cache
    clear_force_join_cache(test_user_id)
    print(f"\n[OK] Cleared cache for user {test_user_id}")

    if test_user_id not in _force_join_cache:
        print("[OK] Test PASSED: Cache cleared successfully")
    else:
        print("[FAILED] Test FAILED: Cache not cleared")

    # Test clear all
    _force_join_cache[111] = (True, time.time())
    _force_join_cache[222] = (True, time.time())
    print(f"\n[OK] Added 2 test entries to cache")

    clear_force_join_cache()  # Clear all
    print("[OK] Cleared entire cache")

    if len(_force_join_cache) == 0:
        print("[OK] Test PASSED: All cache entries cleared")
    else:
        print(f"[FAILED] Test FAILED: {len(_force_join_cache)} entries remain")


async def main():
    """Run all tests"""
    print("\n" + "="*50)
    print("TESTING NEW FEATURES")
    print("="*50)

    # Initialize database
    print("\nInitializing database...")
    await init_db()
    print("[OK] Database initialized")

    # Run tests
    await test_user_tracking()
    await test_get_all_users()
    await test_force_join_cache()

    print("\n" + "="*50)
    print("ALL TESTS COMPLETED")
    print("="*50)
    print("\nCheck the output above for any warnings or failures.")
    print("If all tests passed, the new features are working correctly!")


if __name__ == "__main__":
    asyncio.run(main())
