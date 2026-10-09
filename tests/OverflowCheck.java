import io.brunnodev.ledger.BankPlatform;
public final class OverflowCheck {
 public static void main(String[] args) {
  var engine=new BankPlatform.Engine(new byte[32]);
  engine.addAccount(new BankPlatform.Account("source","BRL",100));
  engine.addAccount(new BankPlatform.Account("target","BRL",Long.MAX_VALUE-10));
  engine.submit("first","source","target",new BankPlatform.Money("BRL",10));
  boolean rejected=false;
  try {engine.submit("second","source","target",new BankPlatform.Money("BRL",1));} catch(ArithmeticException error) {rejected=true;}
  assert rejected;
  assert engine.balance("source").minorUnits()==90;
  assert engine.ledger().size()==2;
  engine.dispatch(new BankPlatform.SandboxRail(),100);
  assert engine.balance("target").minorUnits()==Long.MAX_VALUE;
  assert engine.verifyLedger();
 }
}
