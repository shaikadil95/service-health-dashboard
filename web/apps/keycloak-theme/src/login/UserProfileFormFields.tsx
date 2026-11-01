import { Fragment, useEffect, type Dispatch } from "react"
import type { Attribute } from "keycloakify/login/KcContext"
import {
  getButtonToDisplayForMultivaluedAttributeField,
  useUserProfileForm,
  type FormAction,
  type FormFieldError,
} from "keycloakify/login/lib/useUserProfileForm"
import type { UserProfileFormFieldsProps } from "keycloakify/login/UserProfileFormFieldsProps"

import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"

import { classes } from "./classes"
import { PasswordInput } from "./components/form-field"
import type { I18n } from "./i18n"
import type { KcContext } from "./KcContext"

/**
 * The user profile fields of the registration form (and of the other pages that use them), like
 * Keycloakify's UserProfileFormFields but with the shared components. The input names are the
 * attribute names (firstName, lastName, email, username, password, password-confirm, ...).
 */
export default function UserProfileFormFields(
  props: UserProfileFormFieldsProps<KcContext, I18n>
) {
  const {
    kcContext,
    i18n,
    onIsFormSubmittableValueChange,
    doMakeUserConfirmPassword,
  } = props
  const { advancedMsg } = i18n

  const {
    formState: { formFieldStates, isFormSubmittable },
    dispatchFormAction,
  } = useUserProfileForm({ kcContext, i18n, doMakeUserConfirmPassword })

  useEffect(() => {
    onIsFormSubmittableValueChange(isFormSubmittable)
  }, [isFormSubmittable, onIsFormSubmittableValueChange])

  return (
    <>
      {formFieldStates.map(
        ({ attribute, displayableErrors, valueOrValues }, index) => {
          const { annotations } = attribute
          const previousGroup =
            formFieldStates[index - 1]?.attribute.group?.name
          const groupHeader =
            attribute.group !== undefined &&
            attribute.group.name !== previousGroup ? (
              <div className="grid gap-1 pt-2">
                <p className="text-sm font-semibold">
                  {attribute.group.displayHeader
                    ? advancedMsg(attribute.group.displayHeader)
                    : attribute.group.name}
                </p>
                {attribute.group.displayDescription && (
                  <p className="text-sm text-muted-foreground">
                    {advancedMsg(attribute.group.displayDescription)}
                  </p>
                )}
              </div>
            ) : null

          if (
            annotations.inputType === "hidden" ||
            (attribute.name === "password-confirm" &&
              !doMakeUserConfirmPassword)
          ) {
            return (
              <Fragment key={attribute.name}>
                {groupHeader}
                <input
                  type="hidden"
                  name={attribute.name}
                  value={valueOrValues}
                />
              </Fragment>
            )
          }

          const errorId = `input-error-${attribute.name}`
          const errors = displayableErrors.filter(
            (e) => e.fieldIndex === undefined
          )
          const describedBy =
            [
              annotations.inputHelperTextBefore &&
                `form-help-text-before-${attribute.name}`,
              errors.length > 0 && errorId,
              annotations.inputHelperTextAfter &&
                `form-help-text-after-${attribute.name}`,
            ]
              .filter(Boolean)
              .join(" ") || undefined

          return (
            <Fragment key={attribute.name}>
              {groupHeader}
              <div className="grid gap-2">
                <Label htmlFor={attribute.name}>
                  {advancedMsg(attribute.displayName ?? "")}
                  {attribute.required && (
                    <span aria-hidden="true" className="-ml-1 text-destructive">
                      *
                    </span>
                  )}
                </Label>
                {annotations.inputHelperTextBefore && (
                  <p
                    id={`form-help-text-before-${attribute.name}`}
                    className="text-sm text-muted-foreground"
                  >
                    {advancedMsg(annotations.inputHelperTextBefore)}
                  </p>
                )}
                <FieldInput
                  attribute={attribute}
                  valueOrValues={valueOrValues}
                  displayableErrors={displayableErrors}
                  dispatchFormAction={dispatchFormAction}
                  i18n={i18n}
                  describedBy={describedBy}
                />
                {errors.length > 0 && (
                  <p
                    id={errorId}
                    className="text-sm text-destructive"
                    aria-live="polite"
                  >
                    {errors.map(({ errorMessage }, i) => (
                      <Fragment key={i}>
                        {i > 0 && <br />}
                        {errorMessage}
                      </Fragment>
                    ))}
                  </p>
                )}
                {annotations.inputHelperTextAfter && (
                  <p
                    id={`form-help-text-after-${attribute.name}`}
                    className="text-sm text-muted-foreground"
                  >
                    {advancedMsg(annotations.inputHelperTextAfter)}
                  </p>
                )}
              </div>
            </Fragment>
          )
        }
      )}
    </>
  )
}

type FieldInputProps = {
  attribute: Attribute
  valueOrValues: string | string[]
  displayableErrors: FormFieldError[]
  dispatchFormAction: Dispatch<FormAction>
  i18n: I18n
  describedBy: string | undefined
}

function toInt(value: number | string | undefined) {
  return value === undefined ? undefined : parseInt(`${value}`)
}

function optionsOf(attribute: Attribute): string[] {
  const { inputOptionsFromValidation } = attribute.annotations
  if (inputOptionsFromValidation !== undefined) {
    const validator = (
      attribute.validators as Record<string, { options?: string[] }>
    )[inputOptionsFromValidation]
    if (validator?.options !== undefined) return validator.options
  }
  return attribute.validators.options?.options ?? []
}

function optionLabel(i18n: I18n, attribute: Attribute, option: string) {
  const { inputOptionLabels, inputOptionLabelsI18nPrefix } =
    attribute.annotations
  if (inputOptionLabels !== undefined) {
    return i18n.advancedMsg(inputOptionLabels[option] ?? option)
  }
  if (inputOptionLabelsI18nPrefix !== undefined) {
    return i18n.advancedMsg(`${inputOptionLabelsI18nPrefix}.${option}`)
  }
  return option
}

function FieldInput(props: FieldInputProps) {
  const {
    attribute,
    valueOrValues,
    displayableErrors,
    dispatchFormAction,
    i18n,
    describedBy,
  } = props
  const { annotations, name } = attribute
  const invalid = displayableErrors.length > 0
  const update = (value: string | string[]) =>
    dispatchFormAction({ action: "update", name, valueOrValues: value })
  const blur = (fieldIndex?: number) =>
    dispatchFormAction({ action: "focus lost", name, fieldIndex })

  switch (annotations.inputType) {
    case "textarea":
      return (
        <textarea
          id={name}
          name={name}
          className={classes.kcTextareaClass}
          value={valueOrValues}
          disabled={attribute.readOnly}
          rows={toInt(annotations.inputTypeRows)}
          cols={toInt(annotations.inputTypeCols)}
          maxLength={toInt(annotations.inputTypeMaxlength)}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onChange={(e) => update(e.target.value)}
          onBlur={() => blur()}
        />
      )
    case "select":
    case "multiselect": {
      const multiple = annotations.inputType === "multiselect"
      return (
        <select
          id={name}
          name={name}
          className={`${classes.kcInputClass} ${multiple ? "h-auto" : ""}`}
          value={valueOrValues}
          multiple={multiple}
          size={toInt(annotations.inputTypeSize)}
          disabled={attribute.readOnly}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onChange={(e) =>
            update(
              multiple
                ? Array.from(e.target.selectedOptions, (o) => o.value)
                : e.target.value
            )
          }
          onBlur={() => blur()}
        >
          {!multiple && <option value="" />}
          {optionsOf(attribute).map((option) => (
            <option key={option} value={option}>
              {optionLabel(i18n, attribute, option)}
            </option>
          ))}
        </select>
      )
    }
    case "select-radiobuttons":
    case "multiselect-checkboxes": {
      const type =
        annotations.inputType === "select-radiobuttons" ? "radio" : "checkbox"
      return (
        <div
          role={type === "radio" ? "radiogroup" : "group"}
          aria-describedby={describedBy}
          className="grid gap-2"
        >
          {optionsOf(attribute).map((option) => (
            <label
              key={option}
              htmlFor={`${name}-${option}`}
              className="flex items-center gap-2 text-sm"
            >
              <input
                type={type}
                id={`${name}-${option}`}
                name={name}
                value={option}
                className={classes.kcCheckboxInputClass}
                disabled={attribute.readOnly}
                aria-invalid={invalid}
                checked={
                  valueOrValues instanceof Array
                    ? valueOrValues.includes(option)
                    : valueOrValues === option
                }
                onChange={(e) => {
                  if (valueOrValues instanceof Array) {
                    update(
                      e.target.checked
                        ? [...valueOrValues, option]
                        : valueOrValues.filter((v) => v !== option)
                    )
                  } else {
                    update(e.target.checked ? option : "")
                  }
                }}
                onBlur={() => blur()}
              />
              {optionLabel(i18n, attribute, option)}
            </label>
          ))}
        </div>
      )
    }
  }

  const inputProps = {
    name,
    disabled: attribute.readOnly,
    autoComplete: attribute.autocomplete,
    placeholder:
      annotations.inputTypePlaceholder === undefined
        ? undefined
        : i18n.advancedMsgStr(annotations.inputTypePlaceholder),
    pattern: annotations.inputTypePattern,
    size: toInt(annotations.inputTypeSize),
    maxLength: toInt(annotations.inputTypeMaxlength),
    minLength: toInt(annotations.inputTypeMinlength),
    max: annotations.inputTypeMax,
    min: annotations.inputTypeMin,
    step: annotations.inputTypeStep,
    ...Object.fromEntries(
      Object.entries(attribute.html5DataAnnotations ?? {}).map(([k, v]) => [
        `data-${k}`,
        v,
      ])
    ),
  }

  if (name === "password" || name === "password-confirm") {
    return (
      <PasswordInput
        id={name}
        i18n={i18n}
        {...inputProps}
        value={valueOrValues as string}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        onChange={(e) => update(e.target.value)}
        onBlur={() => blur()}
      />
    )
  }

  const type = annotations.inputType?.startsWith("html5-")
    ? annotations.inputType.slice(6)
    : (annotations.inputType ?? "text")

  if (!(valueOrValues instanceof Array)) {
    return (
      <Input
        id={name}
        type={type}
        {...inputProps}
        value={valueOrValues}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        onChange={(e) => update(e.target.value)}
        onBlur={() => blur()}
      />
    )
  }

  // Multivalued attribute: one input per value, with add/remove buttons.
  return (
    <div className="grid gap-2">
      {valueOrValues.map((value, i) => {
        const errors = displayableErrors.filter((e) => e.fieldIndex === i)
        const errorId = `input-error-${name}-${i}`
        const { hasAdd, hasRemove } =
          getButtonToDisplayForMultivaluedAttributeField({
            attribute,
            values: valueOrValues,
            fieldIndex: i,
          })
        return (
          <div key={i} className="grid gap-1">
            <div className="flex gap-1">
              <Input
                id={i === 0 ? name : `${name}-${i}`}
                type={type}
                {...inputProps}
                value={value}
                aria-label={
                  i === 0
                    ? undefined
                    : `${i18n.advancedMsgStr(attribute.displayName ?? name)} ${i + 1}`
                }
                aria-invalid={errors.length > 0}
                aria-describedby={errors.length > 0 ? errorId : describedBy}
                onChange={(e) =>
                  update(
                    valueOrValues.map((v, j) => (j === i ? e.target.value : v))
                  )
                }
                onBlur={() => blur(i)}
              />
              {hasRemove && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  id={`kc-remove-${name}-${i + 1}`}
                  onClick={() =>
                    update(valueOrValues.filter((_, j) => j !== i))
                  }
                >
                  {i18n.msg("remove")}
                </Button>
              )}
              {hasAdd && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  id={`kc-add-${name}-${i + 1}`}
                  onClick={() => update([...valueOrValues, ""])}
                >
                  {i18n.msg("addValue")}
                </Button>
              )}
            </div>
            {errors.length > 0 && (
              <p id={errorId} className="text-sm text-destructive">
                {errors.map(({ errorMessage }, j) => (
                  <Fragment key={j}>
                    {j > 0 && <br />}
                    {errorMessage}
                  </Fragment>
                ))}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
