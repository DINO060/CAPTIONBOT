"""
Database migration script to add last_activity column to existing databases.
Run this once if you have an existing database without the last_activity column.
"""
import asyncio
import aiosqlite
import os
from datetime import datetime

DB_PATH = os.environ.get("SQLITE_PATH", "autocaption.db")


async def migrate():
    """Add last_activity column to users table if it doesn't exist"""
    db = await aiosqlite.connect(DB_PATH)

    try:
        # Check if column exists
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        if "last_activity" not in column_names:
            print("Adding last_activity column to users table...")
            now = datetime.now().isoformat(timespec="seconds")

            # Add the column with default value
            await db.execute("ALTER TABLE users ADD COLUMN last_activity TEXT")

            # Set last_activity to joined_date for existing users
            await db.execute(
                "UPDATE users SET last_activity = COALESCE(joined_date, ?)",
                (now,)
            )

            await db.commit()
            print("[OK] Migration completed successfully!")
            print("   - Added last_activity column")

            # Show count
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            count = (await cursor.fetchone())[0]
            print(f"   - Updated {count} existing users")
        else:
            print("[OK] Database is already up to date!")

    except Exception as e:
        print(f"[ERROR] Migration failed: {e}")
    finally:
        await db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Database Migration Tool")
    print("=" * 50)
    print(f"Database: {DB_PATH}")
    print()

    asyncio.run(migrate())

    print()
    print("Migration process complete.")
    print("=" * 50)
