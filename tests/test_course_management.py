import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.main import CoursePayload, CourseUpdatePayload, create_course, update_course


class Cursor:
    def __init__(self, row=None, lastrowid=None):
        self.row = row
        self.lastrowid = lastrowid

    def fetchone(self):
        return self.row


class FakeDatabase:
    def __init__(self, course=None):
        self.course = course
        self.last_write = None
        self.committed = False
        self.closed = False

    def execute(self, sql, params=()):
        if sql.startswith("INSERT INTO courses"):
            self.course = {
                "id": 7,
                "title": params[0],
                "description": params[1],
                "teacher": params[2],
                "category": params[3],
            }
            self.last_write = (sql, params)
            return Cursor(lastrowid=7)
        if sql.startswith("SELECT 1 FROM courses"):
            return Cursor({"exists": 1} if self.course else None)
        if sql.startswith("UPDATE courses"):
            self.course["title"] = params[0]
            self.course["description"] = params[1]
            self.last_write = (sql, params)
            return Cursor()
        if sql.startswith("SELECT * FROM courses"):
            return Cursor(self.course)
        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class CourseManagementTests(unittest.TestCase):
    def test_create_course_trims_form_values(self):
        database = FakeDatabase()
        payload = CoursePayload(
            title="  新课程  ",
            description="  课程介绍  ",
            teacher="  王老师  ",
            category="  编程  ",
        )

        with patch("app.main.db", return_value=database):
            result = create_course(payload, {"role": "admin"})

        self.assertEqual(result["title"], "新课程")
        self.assertEqual(result["description"], "课程介绍")
        self.assertTrue(database.committed)
        self.assertTrue(database.closed)

    def test_update_course_changes_title_and_description(self):
        database = FakeDatabase({"id": 7, "title": "旧名称", "description": "旧介绍"})

        with patch("app.main.db", return_value=database):
            result = update_course(7, CourseUpdatePayload(title="新名称", description="新介绍"), {"role": "admin"})

        self.assertEqual(result["title"], "新名称")
        self.assertEqual(result["description"], "新介绍")
        self.assertTrue(database.committed)

    def test_update_course_rejects_missing_course(self):
        database = FakeDatabase()

        with patch("app.main.db", return_value=database):
            with self.assertRaises(HTTPException) as raised:
                update_course(999, CourseUpdatePayload(title="新名称", description="新介绍"), {"role": "admin"})

        self.assertEqual(raised.exception.status_code, 404)
        self.assertTrue(database.closed)

    def test_create_course_rejects_blank_title(self):
        with self.assertRaises(HTTPException) as raised:
            create_course(CoursePayload(title="  ", description="介绍"), {"role": "admin"})

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
