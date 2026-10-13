package example.web;

import example.service.QuoteService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
public class QuoteController {

    private final QuoteService quoteService;

    public QuoteController(QuoteService quoteService) {
        this.quoteService = quoteService;
    }

    @GetMapping("/api/quote")
    public Map<String, Integer> getQuote(
            @RequestParam(name = "sku") String sku,
            @RequestParam(name = "quantity") int quantity) {
        int totalCents = quoteService.quote(sku, quantity);
        return Map.of("totalCents", totalCents);
    }
}
