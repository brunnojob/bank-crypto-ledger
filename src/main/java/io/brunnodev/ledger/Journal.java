package io.brunnodev.ledger;

import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;

public final class Journal {
    public record Line(String account, String currency, long minorUnits) {
        public Line {
            if (!account.matches("[a-zA-Z0-9_-]{1,80}") || !currency.matches("[A-Z]{3}") || minorUnits == 0)
                throw new IllegalArgumentException("invalid posting line");
        }
    }
    public record Entry(String key, Instant timestamp, List<Line> lines) {
        public Entry {
            if (!key.matches("[a-zA-Z0-9_-]{1,128}") || lines.size() < 2 || lines.size() > 100)
                throw new IllegalArgumentException("invalid journal entry");
            var totals = new HashMap<String, Long>();
            for (Line line : lines) totals.merge(line.currency(), line.minorUnits(), Math::addExact);
            if (totals.values().stream().anyMatch(total -> total != 0)) throw new IllegalArgumentException("debits and credits must balance per currency");
            lines = List.copyOf(lines);
        }
    }
    private final Path path;
    public Journal(Path path) { this.path = path; }
    private static String payload(Entry e) {
        return e.key() + "|" + e.timestamp() + "|" + String.join(";", e.lines().stream()
            .map(line -> line.account() + "," + line.currency() + "," + line.minorUnits()).toList());
    }
    private static String hash(String text) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));
    }
    private static List<Entry> replay(FileChannel channel) throws Exception {
        if (channel.size() > 64 * 1024 * 1024) throw new IllegalStateException("journal exceeds 64 MiB");
        ByteBuffer buffer = ByteBuffer.allocate((int) channel.size()); channel.position(0);
        while (buffer.hasRemaining()) if (channel.read(buffer) < 0) break;
        String data = new String(buffer.array(), StandardCharsets.UTF_8);
        if (!data.isEmpty() && !data.endsWith("\n")) throw new IllegalStateException("partial journal append");
        var entries = new ArrayList<Entry>(); var keys = new HashSet<String>(); String previous = "0".repeat(64);
        for (String row : data.split("\n")) {
            if (row.isEmpty()) continue;
            String[] f = row.split("\\|", -1);
            if (f.length != 5 || !f[3].equals(previous) || !f[4].equals(hash(String.join("|", Arrays.copyOf(f, 4)))))
                throw new IllegalStateException("journal hash chain invalid");
            var lines = new ArrayList<Line>();
            for (String encoded : f[2].split(";")) {
                String[] l = encoded.split(",", -1);
                if (l.length != 3) throw new IllegalStateException("invalid posting");
                lines.add(new Line(l[0], l[1], Long.parseLong(l[2])));
            }
            if (!keys.add(f[0])) throw new IllegalStateException("duplicate entry key");
            entries.add(new Entry(f[0], Instant.parse(f[1]), lines)); previous = f[4];
        }
        return entries;
    }
    public boolean append(Entry entry) throws Exception {
        try (FileChannel channel = FileChannel.open(path, StandardOpenOption.CREATE, StandardOpenOption.READ, StandardOpenOption.WRITE);
             var lock = channel.lock()) {
            if (!lock.isValid()) throw new IllegalStateException("journal lock unavailable");
            List<Entry> entries = replay(channel);
            for (Entry prior : entries) if (prior.key().equals(entry.key())) {
                if (!prior.lines().equals(entry.lines())) throw new IllegalStateException("idempotency conflict");
                return false;
            }
            String previous = "0".repeat(64);
            if (!entries.isEmpty()) {
                channel.position(0); ByteBuffer bytes = ByteBuffer.allocate((int) channel.size());
                while (bytes.hasRemaining()) channel.read(bytes);
                String[] rows = new String(bytes.array(), StandardCharsets.UTF_8).strip().split("\n");
                previous = rows[rows.length-1].split("\\|")[4];
            }
            var balances = balances(entries);
            for (Line line : entry.lines()) balances.merge(line.account() + ":" + line.currency(), line.minorUnits(), Math::addExact);
            String payload = payload(entry) + "|" + previous;
            ByteBuffer bytes = ByteBuffer.wrap((payload + "|" + hash(payload) + "\n").getBytes(StandardCharsets.UTF_8));
            channel.position(channel.size()); while (bytes.hasRemaining()) channel.write(bytes); channel.force(true); return true;
        }
    }
    private static Map<String, Long> balances(List<Entry> entries) {
        var balances = new TreeMap<String, Long>();
        for (Entry entry : entries) for (Line line : entry.lines()) balances.merge(line.account() + ":" + line.currency(), line.minorUnits(), Math::addExact);
        return balances;
    }
    public Map<String, Long> balances() throws Exception {
        try (FileChannel channel = FileChannel.open(path, StandardOpenOption.CREATE, StandardOpenOption.READ, StandardOpenOption.WRITE);
             var lock = channel.lock()) {
            if (!lock.isValid()) throw new IllegalStateException("journal lock unavailable");
            return Collections.unmodifiableMap(balances(replay(channel)));
        }
    }
    public static void main(String[] args) throws Exception {
        if (args.length < 2) throw new IllegalArgumentException("Journal file report | post key source destination currency minor-units");
        var journal = new Journal(Path.of(args[0]));
        if (args[1].equals("post")) {
            if (args.length != 7) throw new IllegalArgumentException("invalid post arguments");
            long amount = Long.parseLong(args[6]); if (amount < 1) throw new IllegalArgumentException("positive amount required");
            journal.append(new Entry(args[2], Instant.now(), List.of(new Line(args[3], args[5], -amount), new Line(args[4], args[5], amount))));
        } else if (!args[1].equals("report")) throw new IllegalArgumentException("unknown command");
        System.out.print("{\"balancesMinor\":{"); int i=0;
        for (var balance : journal.balances().entrySet()) { if(i++>0)System.out.print(",");System.out.print("\""+balance.getKey()+"\":"+balance.getValue()); }
        System.out.println("},\"balanced\":true}");
    }
}
