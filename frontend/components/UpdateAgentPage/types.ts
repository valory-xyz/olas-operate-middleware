export enum ElementType {
  HEADER = 'header',
  TEXTAREA = 'textarea',
  INPUT_TEXT = 'input_text',
  INPUT_PASSWORD = 'input_password',
  ALERT_WARNING = 'alert_warning',
}

export type Dynamic = Partial<{
  editable: boolean;
  editingProps: {
    hidden: boolean;
  };
  readProps: {
    link: {
      base?: string;
      external?: boolean;
      formatter?: (value: string) => React.ReactNode;
    };
  };
}>;

export type DynamicInput = {
  id?: string;
  label: string;
  type: `input_${string}`;
  prefix?: React.ReactNode;
} & Dynamic;

export type DynamicAlert = {
  id?: string;
  header?: string;
  content?: string;
  type: `alert_${string}`;
} & Dynamic;

export type DynamicHeader = {
  id?: string;
  type: ElementType.HEADER;
  header: string;
  description?: string;
} & Dynamic;

export type DynamicTextArea = {
  id?: string;
  label: string;
  value?: string;
  type: ElementType.TEXTAREA;
} & Dynamic;

export type DynamicElement =
  | DynamicInput
  | DynamicAlert
  | DynamicHeader
  | DynamicTextArea;
