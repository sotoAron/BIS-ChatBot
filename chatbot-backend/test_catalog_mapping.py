import asyncio
from app.services.moodle_client import get_moodle_client
from app.rag.catalog import get_catalog

async def run():
    m = get_moodle_client()
    courses = await m.get_user_courses(1)
    cat = get_catalog()
    for c in courses:
        course_name = c.get('fullname', '')
        materia_id = cat.normalize_materia(course_name)
        materias_found = cat.find_materias_in_text(course_name)
        print(f"Course: {course_name}")
        print(f"  normalize_materia: {materia_id}")
        print(f"  find_materias: {materias_found}")

if __name__ == '__main__':
    asyncio.run(run())
