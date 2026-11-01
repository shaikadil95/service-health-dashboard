import { createGetKcContextMock } from "keycloakify/login/KcContext"

import { kcEnvDefaults, themeNames } from "../kc.gen"
import type { KcContextExtension, KcContextExtensionPerPage } from "./KcContext"

const kcContextExtension: KcContextExtension = {
  themeName: themeNames[0],
  properties: { ...kcEnvDefaults },
}
const kcContextExtensionPerPage: KcContextExtensionPerPage = {}

// Mock contexts for `pnpm dev` and the tests: the customers realm as configured in the cluster.
export const { getKcContextMock } = createGetKcContextMock({
  kcContextExtension,
  kcContextExtensionPerPage,
  overrides: {
    realm: {
      name: "customers",
      displayName: "Service Health Shop",
      internationalizationEnabled: false,
    },
  },
  overridesPerPage: {
    "login.ftl": {
      realm: {
        registrationAllowed: true,
        resetPasswordAllowed: true,
        rememberMe: false,
      },
    },
  },
})
