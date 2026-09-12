/* Gen1-only policy adapter around the unchanged official UPR handler.
 * Source: UPR ZX v4.6.1 Gen1RomHandler.getStaticPokemon/setTrainers;
 * gen1_offsets.ini Red/Blue/Yellow (U); Gen1Constants champion offset 0x44.
 * The pinned clean hash is required before interpreting these locations.
 */
import com.dabomstew.pkrandom.romhandlers.Gen1RomHandler;
import com.dabomstew.pkrandom.pokemon.StaticEncounter;
import com.dabomstew.pkrandom.pokemon.Trainer;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.List;
import java.util.Random;

public final class SLinkGen1RomHandler extends Gen1RomHandler {
    public SLinkGen1RomHandler(Random random) { super(random); }

    @Override public boolean loadRom(String filename) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-1").digest(Files.readAllBytes(Paths.get(filename)));
            StringBuilder hex = new StringBuilder();
            for (byte value : hash) hex.append(String.format("%02x", value & 255));
            String digest = hex.toString();
            if (!digest.equals("ea9bcae617fdf159b045185467ae58b2e4a48b9a")
                    && !digest.equals("d7037c83e1ae5b39bde3c30787637ba1d4c48ce2")
                    && !digest.equals("cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1"))
                throw new IllegalArgumentException("Gen1 generation requires a pinned clean R/B/Y input");
        } catch (java.io.IOException | java.security.NoSuchAlgorithmException error) {
            throw new IllegalStateException("cannot verify Gen1 source", error);
        }
        return super.loadRom(filename);
    }

    @Override public List<StaticEncounter> getStaticPokemon() {
        List<StaticEncounter> encounters = super.getStaticPokemon();
        // The source config places the uncatchable Tower ghost last. Restrict
        // that entry through UPR's own public pool API so its log stays truthful.
        if (encounters.size() != (isYellow() ? 32 : 29))
            throw new IllegalStateException("Gen1 static inventory differs");
        StaticEncounter ghost = encounters.get(encounters.size()-1);
        if (ghost.pkmn.number != 105 || ghost.level != 30)
            throw new IllegalStateException("canonical uncatchable Tower ghost differs");
        ghost.restrictedPool = true;
        ghost.restrictedList.add(ghost.pkmn);
        return encounters;
    }

    @Override public void setTrainers(List<Trainer> trainers, boolean doubleBattleMode) {
        // Stock UPR clears these overrides whenever it writes a trainer party,
        // even with betterTrainerMovesets=false. Preserve the original engine
        // tables/branch while retaining UPR's party and level serialization.
        int moves = isYellow() ? 0x39C6B : 0x39D32;
        int champion = 0x39D23-0x44;
        byte moveByte = rom[moves], branch = rom[champion], operand = rom[champion+1];
        try { super.setTrainers(trainers, doubleBattleMode); }
        finally {
            rom[moves] = moveByte;
            if (!isYellow()) { rom[champion] = branch; rom[champion+1] = operand; }
        }
    }

    @Override public void setTMMoves(List<Integer> moves) {
        // TM assignment must not also replace Red/Blue gym leaders' forced moves.
        byte[] original = new byte[8];
        if (!isYellow()) for (int i=0; i<8; i++) original[i] = rom[0x39D23+i*2];
        try { super.setTMMoves(moves); }
        finally {
            if (!isYellow()) for (int i=0; i<8; i++) rom[0x39D23+i*2] = original[i];
        }
        if (isYellow() && rom[0xAE66B] != originalRom[0xAE66B]) {
            // Yellow TM48's source text allocation is 22 bytes. UPR's template
            // needs 23 for a 12-byte move name. Drop only the exclamation mark
            // and retain the complete move name and following dialogue opcode.
            if (rom[0xAE66B] != 0x57 || (rom[0xAE66A] & 255) != 0xE7)
                throw new IllegalStateException("unexpected Yellow TM48 text overflow");
            rom[0xAE66A] = 0x57;
            rom[0xAE66B] = originalRom[0xAE66B];
        }
    }
}
