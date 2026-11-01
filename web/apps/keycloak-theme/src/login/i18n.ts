import { i18nBuilder } from "keycloakify/login"

import type { ThemeName } from "../kc.gen"

/** @see https://docs.keycloakify.dev/features/i18n */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const { useI18n, ofTypeI18n } = i18nBuilder
  .withThemeName<ThemeName>()
  .withCustomTranslations({
    en: {
      shopTagline: "Sign in to place and track your orders",
      backToLogin: "Back to sign in",
    },
  })
  .build()

type I18n = typeof ofTypeI18n

export { useI18n, type I18n }
