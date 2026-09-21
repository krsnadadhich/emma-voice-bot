-- Demo schema, synthetic data only. Re-running this resets the demo data.

DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS slots;
DROP TABLE IF EXISTS orders;

CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_number CHAR(6) NOT NULL UNIQUE,
    customer_name VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL,
    city VARCHAR(100) NOT NULL,
    eta_start DATETIME,
    eta_end DATETIME,
    last_update DATETIME NOT NULL,
    note VARCHAR(255)
);

CREATE TABLE slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kind VARCHAR(20) NOT NULL,
    location VARCHAR(100) NOT NULL,
    slot_time DATETIME NOT NULL,
    is_booked BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_name VARCHAR(100) NOT NULL,
    slot_id INT NOT NULL UNIQUE,
    order_number CHAR(6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (slot_id) REFERENCES slots(id)
);
