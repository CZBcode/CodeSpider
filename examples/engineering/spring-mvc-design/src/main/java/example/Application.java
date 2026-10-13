package example;

import example.domain.BulkPricing;
import example.domain.PricingPolicy;
import example.repository.InMemoryProductRepository;
import example.repository.ProductRepository;
import example.service.QuoteService;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

@SpringBootApplication
public class Application {

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public ProductRepository productRepository() {
        return new InMemoryProductRepository();
    }

    @Bean
    public PricingPolicy pricingPolicy() {
        return new BulkPricing();
    }

    @Bean
    public QuoteService quoteService(ProductRepository repository, PricingPolicy pricing) {
        return new QuoteService(repository, pricing);
    }
}
