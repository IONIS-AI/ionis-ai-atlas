// The top-level sections (SPEC "The shell"). A section appears here once it's built: one that doesn't
// exist yet is absent, not disabled. Each renders its own landing page at `path` (#44), so adding a
// section means adding its entry and its landing content, not reworking the shell.
export const SECTIONS = [
  {
    path: "/adif",
    label: "ADIF Reference",
    // Which ADIF versions are loaded is data (R17): Home lists them from the API, so none is named here.
    about: "ADIF's data types, fields and enumerations, exactly as adif.org publishes them, for each ADIF version this Atlas carries.",
  },
];
