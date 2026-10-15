import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import AppContext


def create_patches(files):
    return [
        {"path": path, "operation": "create", "replacement": content}
        for path, content in files.items()
    ]


def approve_and_wait(context, task):
    context.tasks.approve(task.id)
    context.tasks.executor.shutdown(wait=True)
    return context.tasks.get(task.id)


class FreshGenerationProjectTests(unittest.TestCase):
    def test_fresh_python_multi_module_project_passes_generated_and_independent_tests(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "invoice-python"
            root.mkdir()
            context = AppContext(str(base / "state"))
            self.addCleanup(context.close)
            self.addCleanup(context.processes.close)
            workspace = context.workspaces.create(str(root), description="Python multi-module invoice service")
            files = {
                "billing/__init__.py": "from .service import InvoiceService\n",
                "billing/money.py": '''from decimal import Decimal, ROUND_HALF_UP\n\ndef cents(value):\n    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)\n    if amount < 0:\n        raise ValueError("amount must be non-negative")\n    return int(amount * 100)\n''',
                "billing/service.py": '''from .money import cents\n\nclass InvoiceService:\n    def total_cents(self, items, discount="0"):\n        rate = DecimalDiscount(discount)\n        return rate.apply(sum(cents(item) for item in items))\n\nclass DecimalDiscount:\n    def __init__(self, value):\n        self.value = cents(value)\n        if self.value < 0 or self.value > 10000:\n            raise ValueError("discount must be between 0 and 100")\n\n    def apply(self, total):\n        return (total * (10000 - self.value) + 5000) // 10000\n''',
                "tests/__init__.py": "",
                "tests/test_invoice.py": '''import unittest\nfrom billing.service import InvoiceService\n\nclass InvoiceTests(unittest.TestCase):\n    def test_rounding_and_discount(self):\n        self.assertEqual(InvoiceService().total_cents(["1.005", "0.10"], "10"), 100)\n\n    def test_invalid_discount(self):\n        with self.assertRaises(ValueError):\n            InvoiceService().total_cents(["1"], "101")\n\nif __name__ == "__main__":\n    unittest.main()\n''',
            }
            task = context.tasks.create(workspace.id, "生成多模块账单工程", patches=create_patches(files))
            result = approve_and_wait(context, task)
            self.assertEqual(result.status, "succeeded", result.error)
            self.assertEqual(context.workspaces.get(workspace.id).project_type, "python")

            acceptance = root / "acceptance_invoice.py"
            acceptance.write_text('''import decimal\nfrom billing.service import InvoiceService\n\nservice = InvoiceService()\nassert service.total_cents(["10.00", "0.10"], "12.5") == 884\ntry:\n    service.total_cents(["1"], "NaN")\nexcept Exception as exc:\n    assert isinstance(exc, (ValueError, decimal.InvalidOperation))\nelse:\n    raise AssertionError("invalid discount accepted")\n''', encoding="utf-8")
            # Keep this oracle independent of generated unittest files and run it
            # in a separate interpreter, as the generation benchmark does.
            completed = subprocess.run(["python3", str(acceptance)], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @unittest.skipUnless(shutil.which("mvn"), "Maven is required for the Spring generation case")
    def test_fresh_spring_mvc_project_passes_maven_and_independent_http_oracle(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "discount-spring"
            root.mkdir()
            clean_settings = base / "maven-settings.xml"
            clean_settings.write_text(
                '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0" />', encoding="utf-8"
            )
            context = AppContext(str(base / "state"))
            self.addCleanup(context.close)
            self.addCleanup(context.processes.close)
            workspace = context.workspaces.create(str(root), description="Spring MVC discount API")
            files = {
                "pom.xml": '''<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">\n  <modelVersion>4.0.0</modelVersion>\n  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.4.4</version><relativePath/></parent>\n  <groupId>example</groupId><artifactId>discount-service</artifactId><version>0.0.1-SNAPSHOT</version>\n  <properties><java.version>17</java.version></properties>\n  <dependencies>\n    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>\n    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-test</artifactId><scope>test</scope></dependency>\n  </dependencies>\n  <build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build>\n</project>\n''',
                "src/main/java/example/Application.java": '''package example;\n\nimport org.springframework.boot.SpringApplication;\nimport org.springframework.boot.autoconfigure.SpringBootApplication;\n\n@SpringBootApplication\npublic class Application {\n    public static void main(String[] args) { SpringApplication.run(Application.class, args); }\n}\n''',
                "src/main/java/example/DiscountService.java": '''package example;\n\nimport org.springframework.stereotype.Service;\n\n@Service\npublic class DiscountService {\n    public int apply(int priceCents, int percent) {\n        if (priceCents < 0 || percent < 0 || percent > 100) throw new IllegalArgumentException("invalid discount");\n        return (priceCents * (100 - percent) + 50) / 100;\n    }\n}\n''',
                "src/main/java/example/DiscountController.java": '''package example;\n\nimport org.springframework.http.ResponseEntity;\nimport org.springframework.web.bind.annotation.GetMapping;\nimport org.springframework.web.bind.annotation.RequestParam;\nimport org.springframework.web.bind.annotation.RestController;\n\n@RestController\npublic class DiscountController {\n    private final DiscountService service;\n    public DiscountController(DiscountService service) { this.service = service; }\n\n    @GetMapping("/api/discount")\n    public ResponseEntity<DiscountResponse> discount(@RequestParam(name = "priceCents") int priceCents, @RequestParam(name = "percent") int percent) {\n        try { return ResponseEntity.ok(new DiscountResponse(service.apply(priceCents, percent))); }\n        catch (IllegalArgumentException error) { return ResponseEntity.badRequest().build(); }\n    }\n\n    public record DiscountResponse(int priceCents) {}\n}\n''',
                "src/test/java/example/DiscountServiceTest.java": '''package example;\n\nimport org.junit.jupiter.api.Test;\nimport static org.junit.jupiter.api.Assertions.*;\n\nclass DiscountServiceTest {\n    @Test void roundsHalfUp() { assertEquals(900, new DiscountService().apply(1000, 10)); }\n    @Test void rejectsInvalidPercent() { assertThrows(IllegalArgumentException.class, () -> new DiscountService().apply(1000, 101)); }\n}\n''',
            }
            # Keep this case independent from a developer's global Nexus
            # mirror; the generated project still executes through the Agent.
            from engineering_plugins import springboot
            original_verification = springboot.verification
            verifier = patch.object(springboot, "verification", side_effect=lambda root: dict(
                original_verification(root), verify_command="mvn -s %s -q test" % clean_settings))
            verifier.start()
            self.addCleanup(verifier.stop)
            task = context.tasks.create(workspace.id, "生成 Spring MVC 折扣工程", patches=create_patches(files))
            result = approve_and_wait(context, task)
            if result.status != "succeeded":
                outputs = [event.payload.get("output", "") for event in context.tasks.events(task.id) if event.type == "process.output"]
                self.fail((result.error or result.status) + "\n" + "\n".join(outputs))
            self.assertEqual(context.workspaces.get(workspace.id).project_type, "java-springboot")

            oracle = root / "src/test/java/example/DiscountAcceptanceTest.java"
            oracle.write_text('''package example;\n\nimport org.junit.jupiter.api.Test;\nimport org.springframework.beans.factory.annotation.Autowired;\nimport org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;\nimport org.springframework.boot.test.context.SpringBootTest;\nimport org.springframework.test.web.servlet.MockMvc;\nimport static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;\nimport static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;\n\n@SpringBootTest(classes = Application.class)\n@AutoConfigureMockMvc\nclass DiscountAcceptanceTest {\n    @Autowired MockMvc mvc;\n    @Test void appliesDiscount() throws Exception { mvc.perform(get("/api/discount").param("priceCents", "1000").param("percent", "10")).andExpect(status().isOk()).andExpect(jsonPath("$.priceCents").value(900)); }\n    @Test void rejectsInvalidDiscount() throws Exception { mvc.perform(get("/api/discount").param("priceCents", "1000").param("percent", "101")).andExpect(status().isBadRequest()); }\n}\n''', encoding="utf-8")
            completed = subprocess.run(
                ["mvn", "-s", str(clean_settings), "-q", "-Dtest=DiscountAcceptanceTest", "test"],
                cwd=root, capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
