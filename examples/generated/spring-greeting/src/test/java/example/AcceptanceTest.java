package example;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
@SpringBootTest(classes=Application.class)
@AutoConfigureMockMvc
class AcceptanceTest {
 @Autowired MockMvc mvc;
 @Test void defaultName() throws Exception { mvc.perform(get("/api/greet")).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("Hello, world!")); }
 @Test void trimName() throws Exception { mvc.perform(get("/api/greet").param("name","  Ada  ")).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("Hello, Ada!")); }
 @Test void blankName() throws Exception { mvc.perform(get("/api/greet").param("name","   ")).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("Hello, world!")); }
 @Test void inputIsData() throws Exception { mvc.perform(get("/api/greet").param("name","<script>alert(1)</script>")).andExpect(status().isOk()).andExpect(content().contentTypeCompatibleWith("application/json")).andExpect(jsonPath("$.message").value("Hello, <script>alert(1)</script>!")); }
}
