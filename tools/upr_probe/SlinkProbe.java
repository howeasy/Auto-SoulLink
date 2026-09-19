import com.dabomstew.pkrandom.FileFunctions;
import com.dabomstew.pkrandom.RandomSource;
import com.dabomstew.pkrandom.Randomizer;
import com.dabomstew.pkrandom.Settings;
import com.dabomstew.pkrandom.Version;
import com.dabomstew.pkrandom.romhandlers.Gen1RomHandler;
import com.dabomstew.pkrandom.romhandlers.RomHandler;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.util.ResourceBundle;

/**
 * SlinkProbe: a tiny harness compiled against any PokeRandoZX.jar (baseline or fork).
 *
 *   entry <rom>                      prints the Gen 1 RomEntry the jar detects (or "null")
 *   run -i in -o out -s settings -seed N [-l]
 *                                    randomizes with a FIXED seed (the CLI has no seed flag)
 *   version                          prints Version.VERSION_STRING
 */
public class SlinkProbe {
    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            System.err.println("usage: entry <rom> | run -i in -o out -s settings -seed N [-l] | version");
            System.exit(2);
        }
        switch (args[0]) {
            case "version":
                System.out.println(Version.VERSION_STRING);
                return;
            case "entry": {
                Gen1RomHandler.Factory f = new Gen1RomHandler.Factory();
                if (!f.isLoadable(args[1])) {
                    System.out.println("null");
                    return;
                }
                RomHandler rh = f.create(RandomSource.instance());
                rh.loadRom(args[1]);
                System.out.println(rh.getROMName());
                return;
            }
            case "run":
                run(args);
                return;
            default:
                System.err.println("unknown command " + args[0]);
                System.exit(2);
        }
    }

    private static void run(String[] args) throws Exception {
        String in = null, out = null, settingsPath = null;
        long seed = 0;
        boolean saveLog = false;
        for (int i = 1; i < args.length; i++) {
            switch (args[i]) {
                case "-i": in = args[++i]; break;
                case "-o": out = args[++i]; break;
                case "-s": settingsPath = args[++i]; break;
                case "-seed": seed = Long.parseLong(args[++i]); break;
                case "-l": saveLog = true; break;
                default: throw new IllegalArgumentException(args[i]);
            }
        }
        Settings settings;
        try (FileInputStream fis = new FileInputStream(new File(settingsPath))) {
            settings = Settings.read(fis);
        }
        settings.setCustomNames(FileFunctions.getCustomNames());
        Gen1RomHandler.Factory f = new Gen1RomHandler.Factory();
        if (!f.isLoadable(in)) {
            System.err.println("not a Gen 1 ROM this jar knows: " + in);
            System.exit(1);
        }
        RomHandler rh = f.create(RandomSource.instance());
        rh.loadRom(in);
        settings.tweakForRom(rh);
        ResourceBundle bundle = ResourceBundle.getBundle("com/dabomstew/pkrandom/newgui/Bundle");
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        PrintStream log = new PrintStream(baos, false, "UTF-8");
        new Randomizer(settings, rh, bundle, false).randomize(new File(out).getAbsolutePath(), log, seed);
        log.close();
        if (saveLog) {
            try (FileOutputStream fos = new FileOutputStream(out + ".log")) {
                fos.write(0xEF); fos.write(0xBB); fos.write(0xBF);
                fos.write(baos.toByteArray());
            }
        }
        System.out.println("ok seed=" + seed + " entry=" + rh.getROMName());
    }
}
