/* Place SLink injected code at the free-ROM region; slink_hook() must be first
 * (the CallCallbacks hook BLs to CODE_BASE).
 * CODE_BASE is 0x08378F70 (not 0x08378CA8): the RR4.1_Custom Battle Calc owns
 * 0x08378CA8..0x08378F6F, so SLink sits in the 0xFF run that resumes at 0x08378F70.
 * Keep this ORIGIN in sync with CODE_BASE in build.py. */
MEMORY { rom (rx) : ORIGIN = 0x08378F70, LENGTH = 0x14000 }

SECTIONS
{
  .text 0x08378F70 :
  {
    KEEP(*(.text.entry))   /* slink_hook lands exactly at CODE_BASE */
    *(.text*)
    *(.rodata*)
    *(.data*)
  } > rom

  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) *(.note*) }
}
