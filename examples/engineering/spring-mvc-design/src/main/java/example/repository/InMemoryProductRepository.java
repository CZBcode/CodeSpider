package example.repository;

import java.util.NoSuchElementException;

public class InMemoryProductRepository implements ProductRepository {

    @Override
    public int unitPrice(String sku) {
        if ("book".equals(sku)) {
            return 1000;
        }
        throw new NoSuchElementException("Unknown SKU: " + sku);
    }
}
