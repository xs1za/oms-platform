import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from jose import jwt


ROOT = Path(__file__).resolve().parents[3]


def import_oms1_modules(database_url: str):
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    os.environ.update(
        {
            "DATABASE_URL": database_url,
            "ADMIN_INITIAL_PASSWORD": "admin-test-password",
            "OMS2_SERVICE_SECRET": "oms2-test-secret",
            "OMS3_SERVICE_SECRET": "oms3-test-secret",
            "OMS4_SERVICE_SECRET": "oms4-test-secret",
            "OMS5_SERVICE_SECRET": "oms5-test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
            "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:1",
        }
    )
    sys.path.insert(0, str(ROOT / "OMS1"))
    try:
        database = importlib.import_module("app.database")
        models = importlib.import_module("app.models")
        seed = importlib.import_module("app.seed")
        set_service_secret = importlib.import_module("app.set_service_secret")
        set_user_password = importlib.import_module("app.set_user_password")
        main = importlib.import_module("app.main")
        return database, models, seed, set_service_secret, set_user_password, main
    finally:
        sys.path.pop(0)


class Oms1AuthPostgresTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_url = f"sqlite:///{Path(self.temp_dir.name) / 'oms1-auth.sqlite'}"
        self.database, self.models, self.seed, self.set_service_secret, self.set_user_password, self.main = (
            import_oms1_modules(self.database_url)
        )
        self.models.Base.metadata.create_all(self.database.engine)
        with self.database.SessionLocal() as db:
            self.seed.seed_auth_data(db)
        self.main.publish_event = lambda topic, payload: None

    def tearDown(self):
        self.database.engine.dispose()
        self.temp_dir.cleanup()

    def test_seed_is_idempotent_and_stores_only_hashes(self):
        with self.database.SessionLocal() as db:
            second_result = self.seed.seed_auth_data(db)
            users = db.query(self.models.User).all()
            clients = db.query(self.models.ServiceClient).all()

        self.assertEqual(second_result, {"users": 0, "service_clients": 0})
        self.assertEqual(len(users), 1)
        self.assertEqual(len(clients), 4)
        self.assertNotEqual(users[0].password_hash, "admin-test-password")
        self.assertTrue(self.main.password_context.verify("admin-test-password", users[0].password_hash))
        oms2 = next(client for client in clients if client.client_id == "OMS2")
        self.assertNotEqual(oms2.secret_hash, "oms2-test-secret")
        self.assertTrue(self.main.password_context.verify("oms2-test-secret", oms2.secret_hash))

    def test_user_and_service_tokens_use_database_records(self):
        with self.database.SessionLocal() as db:
            user_token = self.main.login(
                self.main.UserLogin(username="admin", password="admin-test-password"), db=db
            )
            service_token = self.main.service_login(
                self.main.ServiceLogin(client_id="OMS2", client_secret="oms2-test-secret"), db=db
            )
            with self.assertRaises(HTTPException) as invalid_response:
                self.main.service_login(self.main.ServiceLogin(client_id="OMS2", client_secret="wrong-secret"), db=db)

        self.assertTrue(user_token.access_token)
        self.assertTrue(service_token.access_token)
        self.assertEqual(invalid_response.exception.status_code, 401)

        payload = jwt.decode(service_token.access_token, "test-jwt-secret", algorithms=["HS256"])
        self.assertEqual(payload["sub"], "OMS2")
        self.assertEqual(payload["typ"], "service")

    def test_management_commands_rotate_user_password_and_service_secret(self):
        self.set_user_password.set_user_password("admin", "new-admin-password")
        self.set_service_secret.set_service_secret("OMS2", "new-oms2-secret")

        with self.database.SessionLocal() as db:
            user = db.query(self.models.User).filter(self.models.User.username == "admin").one()
            client = db.query(self.models.ServiceClient).filter(self.models.ServiceClient.client_id == "OMS2").one()
            self.assertNotEqual(user.password_hash, "new-admin-password")
            self.assertNotEqual(client.secret_hash, "new-oms2-secret")
            self.assertTrue(self.main.password_context.verify("new-admin-password", user.password_hash))
            self.assertTrue(self.main.password_context.verify("new-oms2-secret", client.secret_hash))

            self.assertEqual(
                self.main.login(self.main.UserLogin(username="admin", password="new-admin-password"), db=db).token_type,
                "bearer",
            )
            with self.assertRaises(HTTPException):
                self.main.login(self.main.UserLogin(username="admin", password="admin-test-password"), db=db)

            self.assertEqual(
                self.main.service_login(
                    self.main.ServiceLogin(client_id="OMS2", client_secret="new-oms2-secret"), db=db
                ).token_type,
                "bearer",
            )
            with self.assertRaises(HTTPException):
                self.main.service_login(
                    self.main.ServiceLogin(client_id="OMS2", client_secret="oms2-test-secret"), db=db
                )


if __name__ == "__main__":
    unittest.main()
