import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.Base64;

/** Small line protocol bridge so the standard-library Python app can use H2. */
public final class H2Bridge {
    private static String encode(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private static String decode(String value) {
        return new String(Base64.getDecoder().decode(value), StandardCharsets.UTF_8);
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("database path is required");
        String path = Paths.get(args[0]).toAbsolutePath().toString().replace('\\', '/');
        Class.forName("org.h2.Driver");
        try (Connection connection = DriverManager.getConnection(
                "jdbc:h2:file:" + path + ";MODE=PostgreSQL;AUTO_SERVER=TRUE", "sa", "")) {
            try (Statement statement = connection.createStatement()) {
                statement.executeUpdate("CREATE TABLE IF NOT EXISTS codespider_kv (name VARCHAR(255) PRIMARY KEY, json_value CLOB NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)");
            }
            connection.commit();
            BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
            BufferedWriter output = new BufferedWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8));
            output.write("READY\n");
            output.flush();
            String line;
            while ((line = input.readLine()) != null) {
                try {
                    String[] parts = line.split("\\t", -1);
                    String command = parts[0];
                    if ("GET".equals(command)) {
                        try (PreparedStatement statement = connection.prepareStatement("SELECT json_value FROM codespider_kv WHERE name=?")) {
                            statement.setString(1, parts[1]);
                            try (ResultSet result = statement.executeQuery()) {
                                output.write(result.next() ? "VALUE\t" + encode(result.getString(1)) : "MISSING");
                            }
                        }
                    } else if ("PUT".equals(command)) {
                        try (PreparedStatement statement = connection.prepareStatement("MERGE INTO codespider_kv (name,json_value,updated_at) KEY(name) VALUES (?, ?, CURRENT_TIMESTAMP)")) {
                            statement.setString(1, parts[1]);
                            statement.setString(2, decode(parts[2]));
                            statement.executeUpdate();
                        }
                        connection.commit();
                        output.write("OK");
                    } else {
                        throw new IllegalArgumentException("unknown command");
                    }
                } catch (Exception error) {
                    connection.rollback();
                    output.write("ERROR\t" + encode(error.getMessage() == null ? "database error" : error.getMessage()));
                }
                output.write("\n");
                output.flush();
            }
        }
    }
}
