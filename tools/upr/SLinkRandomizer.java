/* External UPR ZX 4.6.1 bridge. Uses its public API; never modifies/bundles the JAR. */
import com.dabomstew.pkrandom.CustomNamesSet;
import com.dabomstew.pkrandom.RandomSource;
import com.dabomstew.pkrandom.Randomizer;
import com.dabomstew.pkrandom.Settings;
import com.dabomstew.pkrandom.Version;
import com.dabomstew.pkrandom.romhandlers.Gen1RomHandler;
import com.dabomstew.pkrandom.romhandlers.Gen2RomHandler;
import com.dabomstew.pkrandom.romhandlers.Gen3RomHandler;
import com.dabomstew.pkrandom.romhandlers.RomHandler;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ResourceBundle;

public final class SLinkRandomizer {
    public static void main(String[] args) throws Exception {
        if (args.length != 6) throw new IllegalArgumentException("settings input output seed customnames generation required");
        if (!"4.6.1".equals(Version.VERSION_STRING) || Version.VERSION != 322)
            throw new IllegalArgumentException("UPR ZX 4.6.1 required");
        if (!args[3].matches("0|[1-9][0-9]*")) throw new IllegalArgumentException("canonical decimal seed required");
        long seed = Long.parseLong(args[3]);
        if (seed < 0 || seed >= (1L << 48)) throw new IllegalArgumentException("seed outside 48-bit range");
        Path input = Paths.get(args[1]).toRealPath();
        Path output = Paths.get(args[2]).toAbsolutePath().normalize();
        if (Files.exists(output) || input.equals(output)) throw new IllegalArgumentException("new output path required");
        byte[] encoded = Files.readAllBytes(Paths.get(args[0]));
        if (encoded.length < 8 || ByteBuffer.wrap(encoded).getInt() != 322)
            throw new IllegalArgumentException("settings migration is prohibited");
        Settings settings;
        try (FileInputStream stream = new FileInputStream(args[0])) { settings = Settings.read(stream); }
        if (settings.isUpdatedFromOldVersion()) throw new IllegalArgumentException("settings migration is prohibited");
        try (FileInputStream stream = new FileInputStream(args[4])) { settings.setCustomNames(new CustomNamesSet(stream)); }
        RomHandler.Factory[] factories = {new Gen1RomHandler.Factory(), new Gen2RomHandler.Factory(), new Gen3RomHandler.Factory()};
        RomHandler handler = null;
        for (RomHandler.Factory factory : factories) {
            if (factory.isLoadable(input.toString())) {
                handler = factory instanceof Gen1RomHandler.Factory
                        ? new SLinkGen1RomHandler(RandomSource.instance()) : factory.create(RandomSource.instance());
                break;
            }
        }
        if (handler == null) throw new IllegalArgumentException("unsupported Gen1/2/3 input");
        handler.loadRom(input.toString());
        if (!Integer.toString(handler.generationOfPokemon()).equals(args[5]))
            throw new IllegalArgumentException("input differs from requested generation handler");
        if (!output.toString().endsWith("." + handler.getDefaultExtension()))
            throw new IllegalArgumentException("output extension differs from selected ROM handler");
        Settings.TweakForROMFeedback feedback = settings.tweakForRom(handler);
        if (feedback.isChangedStarter() && settings.getStartersMod() == Settings.StartersMod.CUSTOM)
            throw new IllegalArgumentException("custom starter was not available in this ROM");
        ResourceBundle bundle = ResourceBundle.getBundle("com/dabomstew/pkrandom/newgui/Bundle");
        File logFile = new File(output.toString() + ".log");
        if (logFile.exists()) throw new IllegalArgumentException("new log path required");
        try (FileOutputStream stream = new FileOutputStream(logFile)) {
            stream.write(new byte[] {(byte)0xEF, (byte)0xBB, (byte)0xBF});
            try (PrintStream log = new PrintStream(stream, false, "UTF-8")) {
                new Randomizer(settings, handler, bundle, false).randomize(output.toString(), log, seed);
                log.flush();
                if (log.checkError()) throw new IllegalStateException("randomizer log write failed");
            }
        }
        if (!Files.isRegularFile(output)) throw new IllegalStateException("randomizer output is missing");
        System.out.println("SLink bridge completed seed " + seed);
    }
}
