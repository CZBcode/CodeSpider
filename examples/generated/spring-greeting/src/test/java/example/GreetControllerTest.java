package example;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(GreetController.class)
class GreetControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void shouldGreetWithName() throws Exception {
        mockMvc.perform(get("/api/greet").param("name", "Ada"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Hello, Ada!"));
    }

    @Test
    void shouldTrimSpacesFromName() throws Exception {
        mockMvc.perform(get("/api/greet").param("name", "  Ada  "))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Hello, Ada!"));
    }

    @Test
    void shouldDefaultToWorldWhenNameMissing() throws Exception {
        mockMvc.perform(get("/api/greet"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Hello, world!"));
    }

    @Test
    void shouldDefaultToWorldWhenNameBlank() throws Exception {
        mockMvc.perform(get("/api/greet").param("name", "   "))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Hello, world!"));
    }

    @Test
    void shouldTreatHtmlCharsAsPlainData() throws Exception {
        mockMvc.perform(get("/api/greet").param("name", "<b>Ada</b>"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Hello, <b>Ada</b>!"));
    }
}
