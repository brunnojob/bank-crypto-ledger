package io.brunnodev.ledger;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Deque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.locks.ReentrantLock;
import javax.crypto.Mac;

public final class BankPlatform {
    public enum Status { PENDING, SETTLED, FAILED }

    public record Money(String currency, long minorUnits) {
        public Money {
            if (currency == null || !currency.matches("[A-Z]{3}")) throw new IllegalArgumentException("currency must be ISO-4217");
        }
        public static Money parse(String currency, String value) {
            return new Money(currency, new BigDecimal(value).setScale(2, RoundingMode.UNNECESSARY).movePointRight(2).longValueExact());
        }
        public Money plus(Money other) {
            requireCurrency(other);
            return new Money(currency, Math.addExact(minorUnits, other.minorUnits));
        }
        public Money minus(Money other) {
            requireCurrency(other);
            return new Money(currency, Math.subtractExact(minorUnits, other.minorUnits));
        }
        private void requireCurrency(Money other) {
            if (!currency.equals(other.currency)) throw new IllegalArgumentException("currency mismatch");
        }
    }

    public static final class Account {
        private final String id;
        private final String currency;
        private long balance;
        public Account(String id, String currency, long openingBalance) {
            if (id == null || id.isBlank() || openingBalance < 0) throw new IllegalArgumentException("invalid account");
            this.id = id;
            this.currency = currency;
            this.balance = openingBalance;
        }
        public String id() { return id; }
        public synchronized Money balance() { return new Money(currency, balance); }
        private synchronized void add(long delta) { balance = Math.addExact(balance, delta); }
    }

    public record Transfer(String id, String idempotencyKey, String source, String destination, Money amount, Status status, String providerReference) {
        Transfer withStatus(Status next, String reference) {
            return new Transfer(id, idempotencyKey, source, destination, amount, next, reference);
        }
    }

    public record Posting(String transferId, String accountId, Money amount, long sequence, String previousMac, String mac) {}

    public interface BankRail {
        RailResult submit(String transferId, String source, String destination, Money amount);
    }

    public record RailResult(boolean accepted, String reference) {}

    public static final class SandboxRail implements BankRail {
        @Override
        public RailResult submit(String transferId, String source, String destination, Money amount) {
            return new RailResult(!destination.equals("sandbox-decline"), "sandbox-" + transferId);
        }
    }

    public static final class Envelope {
        private final SecretKeySpec key;
        private final SecureRandom random = new SecureRandom();
        public Envelope(byte[] keyBytes) {
            if (keyBytes.length != 32) throw new IllegalArgumentException("AES-256 key must be 32 bytes");
            key = new SecretKeySpec(keyBytes.clone(), "AES");
        }
        public String encrypt(String plaintext, String context) {
            try {
                byte[] nonce = new byte[12];
                random.nextBytes(nonce);
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(128, nonce));
                cipher.updateAAD(context.getBytes(StandardCharsets.UTF_8));
                byte[] ciphertext = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
                byte[] packed = new byte[nonce.length + ciphertext.length];
                System.arraycopy(nonce, 0, packed, 0, nonce.length);
                System.arraycopy(ciphertext, 0, packed, nonce.length, ciphertext.length);
                return Base64.getEncoder().encodeToString(packed);
            } catch (Exception error) {
                throw new IllegalStateException(error);
            }
        }
        public String decrypt(String envelope, String context) {
            try {
                byte[] packed = Base64.getDecoder().decode(envelope);
                byte[] nonce = java.util.Arrays.copyOfRange(packed, 0, 12);
                byte[] ciphertext = java.util.Arrays.copyOfRange(packed, 12, packed.length);
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, nonce));
                cipher.updateAAD(context.getBytes(StandardCharsets.UTF_8));
                return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
            } catch (Exception error) {
                throw new IllegalArgumentException("envelope authentication failed", error);
            }
        }
    }

    public static final class Engine {
        private final ReentrantLock lock = new ReentrantLock(true);
        private final Map<String, Account> accounts = new HashMap<>();
        private final Map<String, Transfer> transfers = new HashMap<>();
        private final Map<String, String> idempotencyFingerprints = new HashMap<>();
        private final Deque<String> outbox = new ArrayDeque<>();
        private final List<Posting> ledger = new ArrayList<>();
        private final byte[] auditKey;
        private String lastMac = "0".repeat(64);
        private long sequence;

        public Engine(byte[] auditKey) {
            if (auditKey.length < 32) throw new IllegalArgumentException("audit key must contain at least 32 bytes");
            this.auditKey = auditKey.clone();
        }

        public void addAccount(Account account) {
            lock.lock();
            try {
                if (accounts.putIfAbsent(account.id(), account) != null) throw new IllegalArgumentException("duplicate account");
            } finally {
                lock.unlock();
            }
        }

        public Transfer submit(String idempotencyKey, String sourceId, String destinationId, Money amount) {
            lock.lock();
            try {
                if (idempotencyKey == null || idempotencyKey.isBlank() || amount.minorUnits() <= 0) throw new IllegalArgumentException("invalid transfer");
                String fingerprint = digest(sourceId + "|" + destinationId + "|" + amount.currency() + "|" + amount.minorUnits());
                String priorId = idempotencyFingerprints.get(idempotencyKey);
                if (priorId != null) {
                    if (!priorId.startsWith(fingerprint + ":")) throw new IllegalArgumentException("idempotency key conflict");
                    return transfers.get(priorId.substring(fingerprint.length() + 1));
                }
                Account source = requireAccount(sourceId);
                Account destination = requireAccount(destinationId);
                if (source == destination || !source.currency.equals(amount.currency()) || !destination.currency.equals(amount.currency())) throw new IllegalArgumentException("account or currency mismatch");
                if (source.balance().minorUnits() < amount.minorUnits()) throw new IllegalStateException("insufficient funds");
                String id = "tr_" + digest(idempotencyKey + "|" + sequence).substring(0, 20);
                source.add(-amount.minorUnits());
                append(id, sourceId, new Money(amount.currency(), -amount.minorUnits()));
                append(id, "clearing:" + amount.currency(), amount);
                Transfer transfer = new Transfer(id, idempotencyKey, sourceId, destinationId, amount, Status.PENDING, null);
                transfers.put(id, transfer);
                idempotencyFingerprints.put(idempotencyKey, fingerprint + ":" + id);
                outbox.addLast(id);
                return transfer;
            } finally {
                lock.unlock();
            }
        }

        public List<Transfer> dispatch(BankRail rail, int maxItems) {
            if (maxItems < 1) throw new IllegalArgumentException("maxItems must be positive");
            lock.lock();
            try {
                List<Transfer> processed = new ArrayList<>();
                while (processed.size() < maxItems && !outbox.isEmpty()) {
                    String id = outbox.peekFirst();
                    Transfer transfer = transfers.get(id);
                    RailResult result = rail.submit(id, transfer.source(), transfer.destination(), transfer.amount());
                    if (result.accepted()) {
                        requireAccount(transfer.destination()).add(transfer.amount().minorUnits());
                        append(id, "clearing:" + transfer.amount().currency(), new Money(transfer.amount().currency(), -transfer.amount().minorUnits()));
                        append(id, transfer.destination(), transfer.amount());
                        transfer = transfer.withStatus(Status.SETTLED, result.reference());
                    } else {
                        requireAccount(transfer.source()).add(transfer.amount().minorUnits());
                        append(id, transfer.source(), transfer.amount());
                        append(id, "clearing:" + transfer.amount().currency(), new Money(transfer.amount().currency(), -transfer.amount().minorUnits()));
                        transfer = transfer.withStatus(Status.FAILED, result.reference());
                    }
                    transfers.put(id, transfer);
                    outbox.removeFirst();
                    processed.add(transfer);
                }
                return List.copyOf(processed);
            } finally {
                lock.unlock();
            }
        }

        public Money balance(String accountId) {
            lock.lock();
            try {
                return requireAccount(accountId).balance();
            } finally {
                lock.unlock();
            }
        }

        public Transfer transfer(String id) {
            lock.lock();
            try {
                return Objects.requireNonNull(transfers.get(id), "transfer not found");
            } finally {
                lock.unlock();
            }
        }

        public List<Posting> ledger() {
            lock.lock();
            try {
                return List.copyOf(ledger);
            } finally {
                lock.unlock();
            }
        }

        public boolean verifyLedger() {
            lock.lock();
            try {
                String prior = "0".repeat(64);
                Map<String, Long> totals = new HashMap<>();
                for (Posting posting : ledger) {
                    if (!posting.previousMac().equals(prior)) return false;
                    String expected = sign(posting.sequence() + "|" + posting.transferId() + "|" + posting.accountId() + "|" + posting.amount().currency() + "|" + posting.amount().minorUnits() + "|" + prior);
                    if (!MessageDigest.isEqual(expected.getBytes(StandardCharsets.UTF_8), posting.mac().getBytes(StandardCharsets.UTF_8))) return false;
                    totals.merge(posting.transferId() + ":" + posting.amount().currency(), posting.amount().minorUnits(), Math::addExact);
                    prior = posting.mac();
                }
                return totals.values().stream().allMatch(total -> total == 0);
            } finally {
                lock.unlock();
            }
        }

        private void append(String transferId, String accountId, Money amount) {
            String mac = sign(sequence + "|" + transferId + "|" + accountId + "|" + amount.currency() + "|" + amount.minorUnits() + "|" + lastMac);
            ledger.add(new Posting(transferId, accountId, amount, sequence++, lastMac, mac));
            lastMac = mac;
        }

        private String sign(String value) {
            try {
                Mac mac = Mac.getInstance("HmacSHA256");
                mac.init(new SecretKeySpec(auditKey, "HmacSHA256"));
                return java.util.HexFormat.of().formatHex(mac.doFinal(value.getBytes(StandardCharsets.UTF_8)));
            } catch (Exception error) {
                throw new IllegalStateException(error);
            }
        }

        private Account requireAccount(String id) {
            Account account = accounts.get(id);
            if (account == null) throw new IllegalArgumentException("unknown account: " + id);
            return account;
        }

        private static String digest(String value) {
            try {
                return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
            } catch (Exception error) {
                throw new IllegalStateException(error);
            }
        }
    }

    public static void main(String[] args) {
        Engine engine = new Engine("local-demo-audit-key-32-bytes-long!".getBytes(StandardCharsets.UTF_8));
        engine.addAccount(new Account("ops-001", "BRL", 500_000));
        engine.addAccount(new Account("vendor-009", "BRL", 0));
        Transfer transfer = engine.submit("demo-001", "ops-001", "vendor-009", Money.parse("BRL", "125.50"));
        engine.dispatch(new SandboxRail(), 100);
        System.out.println(engine.transfer(transfer.id()));
        System.out.println("ledger_valid=" + engine.verifyLedger());
    }
}
