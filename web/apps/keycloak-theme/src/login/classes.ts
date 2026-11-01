import type { ClassKey } from "keycloakify/login"

import { buttonVariants } from "@workspace/ui/components/button"

// Same classes as @workspace/ui's Input and Label (packages/ui/src/components/{input,label}.tsx).
const INPUT =
  "h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 py-1 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40"
const LABEL =
  "flex items-center gap-2 text-sm leading-none font-medium select-none"
const CHECKBOX = "size-4 shrink-0 accent-primary"

/**
 * Tailwind classes for the pages we don't customise: Keycloakify's DefaultPage renders them with
 * these `kc*` class keys (and without PatternFly), so they share the look of the custom pages.
 */
export const classes = {
  kcFormClass: "grid gap-4",
  kcFormGroupClass: "grid gap-2",
  kcFormGroupHeader: "text-sm font-semibold",
  kcContentWrapperClass: "grid gap-1",
  kcLabelWrapperClass: "flex items-center gap-1",
  kcLabelClass: LABEL,
  kcInputWrapperClass: "grid gap-2",
  kcInputClass: INPUT,
  kcTextareaClass: `${INPUT} h-auto min-h-16`,
  kcInputGroup: "flex items-center gap-1",
  kcInputErrorMessageClass: "text-sm text-destructive",
  kcInputHelperTextBeforeClass: "text-sm text-muted-foreground",
  kcInputHelperTextAfterClass: "text-sm text-muted-foreground",
  kcInputClassRadio: "flex items-center gap-2",
  kcInputClassCheckbox: "flex items-center gap-2",
  kcInputClassRadioInput: CHECKBOX,
  kcInputClassCheckboxInput: CHECKBOX,
  kcInputClassRadioLabel: "text-sm",
  kcInputClassCheckboxLabel: "text-sm",
  kcInputClassRadioCheckboxLabelDisabled: "opacity-50",
  kcCheckboxInputClass: CHECKBOX,
  kcCheckInputClass: CHECKBOX,
  kcFormOptionsClass: "text-sm",
  kcFormOptionsWrapperClass:
    "flex flex-wrap items-center gap-2 text-sm text-muted-foreground [&_a]:font-medium [&_a]:text-foreground [&_a]:underline-offset-4 [&_a]:hover:underline",
  kcFormSettingClass: "gap-4",
  kcFormButtonsClass: "flex flex-col gap-2",
  kcFormButtonsWrapperClass: "flex flex-col gap-2",
  kcButtonClass: buttonVariants({ variant: null }),
  kcButtonPrimaryClass:
    "bg-primary text-primary-foreground hover:bg-primary/80",
  kcButtonDefaultClass:
    "border-border bg-background hover:bg-muted hover:text-foreground dark:border-input dark:bg-input/30 dark:hover:bg-input/50",
  kcButtonBlockClass: "w-full",
  kcButtonLargeClass: "",
  kcFormPasswordVisibilityButtonClass: buttonVariants({
    variant: "ghost",
    size: "icon-sm",
  }),
  kcFormPasswordVisibilityIconShow: "shd-icon-eye",
  kcFormPasswordVisibilityIconHide: "shd-icon-eye-off",
  kcFormSocialAccountSectionClass: "grid gap-2",
  kcFormSocialAccountListClass: "grid gap-2",
  kcFormSocialAccountListButtonClass: `${buttonVariants({ variant: "outline" })} w-full`,
  kcFormSocialAccountNameClass: "truncate",
  kcSelectAuthListClass: "grid gap-2",
  kcSelectAuthListItemClass:
    "flex w-full items-center gap-3 rounded-lg border p-3 text-left hover:bg-muted",
  kcSelectAuthListItemBodyClass: "grid flex-1 gap-0.5",
  kcSelectAuthListItemHeadingClass: "font-medium",
  kcSelectAuthListItemDescriptionClass: "text-sm text-muted-foreground",
  kcSelectAuthListItemFillClass: "flex-1",
  kcLoginOTPListClass: "grid gap-2",
  kcLoginOTPListItemHeaderClass: "flex items-center gap-2",
  kcLoginOTPListItemTitleClass: "font-medium",
  kcRecoveryCodesList: "grid grid-cols-2 gap-1 font-mono text-sm",
  kcRecoveryCodesActions: "flex gap-2",
  kcRecoveryCodesWarning: "text-sm text-amber-600 dark:text-amber-400",
  kcAlertClass: "rounded-lg border px-2.5 py-2 text-sm",
} satisfies { [key in ClassKey]?: string }
