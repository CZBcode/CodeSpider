package example;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class GreetController {

    @GetMapping("/api/greet")
    public Map<String, String> greet(
            @RequestParam(name = "name", defaultValue = "world") String name) {
        String trimmed = name == null ? "" : name.trim();
        if (trimmed.isEmpty()) {
            trimmed = "world";
        }
        return Map.of("message", "Hello, " + trimmed + "!");
    }
}
