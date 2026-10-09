package io.brunnodev.ledger;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class BankPlatformTest {
  private BankPlatform.Engine engine() {
    BankPlatform.Engine engine =
        new BankPlatform.Engine(
            "test-audit-key-with-at-least-32bytes".getBytes(StandardCharsets.UTF_8));
    engine.addAccount(new BankPlatform.Account("source", "BRL", 100_000));
    engine.addAccount(new BankPlatform.Account("target", "BRL", 0));
    return engine;
  }

  @Test
  void transferReservesThenSettlesWithBalancedLedger() {
    var engine = engine();
    var transfer =
        engine.submit("key-1", "source", "target", BankPlatform.Money.parse("BRL", "50.25"));
    assertEquals(-5_025, engine.ledger().get(0).amount().minorUnits());
    assertEquals(94_975, engine.balance("source").minorUnits());
    assertEquals(BankPlatform.Status.PENDING, transfer.status());
    assertEquals(
        BankPlatform.Status.SETTLED,
        engine.dispatch(new BankPlatform.SandboxRail(), 10).get(0).status());
    assertEquals(5_025, engine.transfer(transfer.id()).amount().minorUnits());
    assertEquals(
        5_025,
        engine.ledger().stream()
            .filter(p -> p.accountId().equals("target"))
            .mapToLong(p -> p.amount().minorUnits())
            .sum());
    assertEquals(94_975, engine.balance("source").minorUnits());
    assertEquals(5_025, engine.balance("target").minorUnits());
    assertTrue(engine.verifyLedger());
  }

  @Test
  void idempotencyReturnsSameTransferAndRejectsConflicts() {
    var engine = engine();
    var amount = BankPlatform.Money.parse("BRL", "10.00");
    var first = engine.submit("key-1", "source", "target", amount);
    assertEquals(first, engine.submit("key-1", "source", "target", amount));
    assertThrows(
        IllegalArgumentException.class,
        () -> engine.submit("key-1", "source", "target", BankPlatform.Money.parse("BRL", "11.00")));
  }

  @Test
  void rejectedRailRestoresSourceBalance() {
    var engine = engine();
    engine.addAccount(new BankPlatform.Account("sandbox-decline", "BRL", 0));
    var transfer =
        engine.submit(
            "key-1", "source", "sandbox-decline", BankPlatform.Money.parse("BRL", "10.00"));
    assertEquals(
        BankPlatform.Status.FAILED,
        engine.dispatch(new BankPlatform.SandboxRail(), 1).get(0).status());
    assertEquals(
        0,
        engine.ledger().stream()
            .filter(p -> p.accountId().equals("source"))
            .mapToLong(p -> p.amount().minorUnits())
            .sum());
    assertEquals(1_000, engine.transfer(transfer.id()).amount().minorUnits());
    assertEquals(100_000, engine.balance("source").minorUnits());
    assertTrue(engine.verifyLedger());
  }

  @Test
  void authenticatedEnvelopeRejectsContextChanges() {
    var envelope = new BankPlatform.Envelope(new byte[32]);
    var encrypted = envelope.encrypt("account-reference", "transfer-1");
    assertEquals("account-reference", envelope.decrypt(encrypted, "transfer-1"));
    assertThrows(IllegalArgumentException.class, () -> envelope.decrypt(encrypted, "transfer-2"));
  }
}
