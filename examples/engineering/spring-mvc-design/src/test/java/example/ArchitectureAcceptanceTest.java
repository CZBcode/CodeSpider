package example;
import example.service.QuoteService;
import example.repository.ProductRepository;
import example.domain.BulkPricing;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
@SpringBootTest(classes=Application.class) @AutoConfigureMockMvc
class ArchitectureAcceptanceTest {
 @Autowired MockMvc mvc;
 @Test void httpContracts() throws Exception {
  mvc.perform(get("/api/quote").param("sku","book").param("quantity","2")).andExpect(status().isOk()).andExpect(jsonPath("$.totalCents").value(1800));
  mvc.perform(get("/api/quote").param("sku","missing").param("quantity","1")).andExpect(status().isNotFound());
  mvc.perform(get("/api/quote").param("sku","book").param("quantity","0")).andExpect(status().isBadRequest());
 }
 @Test void injectedCollaborators() {
  AtomicInteger reads=new AtomicInteger();
  ProductRepository repo=sku->{reads.incrementAndGet();return 1000;};
  assertEquals(1800,new QuoteService(repo,new BulkPricing()).quote("book",2));
  assertEquals(1,reads.get());
  assertEquals(7,new QuoteService(repo,(unit,qty)->7).quote("book",2));
 }
 @Test void validationBeforeIo() {
  AtomicInteger reads=new AtomicInteger();
  QuoteService service=new QuoteService(sku->{reads.incrementAndGet();return 1000;},new BulkPricing());
  assertThrows(IllegalArgumentException.class,()->service.quote("book",0));
  assertEquals(0,reads.get());
 }
 @Test void pricingBoundaries() {
  assertEquals(182,new BulkPricing().total(101,2));
  assertEquals(1000,new BulkPricing().total(1000,1));
  assertThrows(IllegalArgumentException.class,()->new BulkPricing().total(-1,2));
 }
}
