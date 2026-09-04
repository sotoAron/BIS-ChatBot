import asyncio
import os
import sys

sys.path.append("/app")
from app.rag.moodle_sync import sync_all_course_documents
from app.services.moodle_client import get_moodle_client

async def main():
    print("Sincronizando todos los cursos...")
    client = get_moodle_client()
    
    # Moodle API doesn't have an easy get_all_courses without admin tokens,
    # and we only have a few courses, let's sync IDs 2 to 5.
    for c_id in range(2, 6):
        print(f"\nSincronizando Curso ID {c_id}")
        try:
            stats = await sync_all_course_documents(c_id, "2026", "ISI")
            print(f"Stats: {stats}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
