from django import forms


class DataUploadForm(forms.Form):
    file_type = forms.ChoiceField(
        choices=[("excel", "Excel (recommended)"), ("csv", "CSV")],
        widget=forms.RadioSelect,
    )

    log_verbose = forms.BooleanField(
        required=False, initial=True, label="Enable verbose logging"
    )

    # CSV fields - one for each model
    inclusion_full_text = forms.FileField(
        required=False,
        label="FullText CSV",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )
    descriptive = forms.FileField(
        required=False,
        label="Descriptive CSV",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )
    host = forms.FileField(
        required=False,
        label="Host CSV",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )
    pathogen = forms.FileField(
        required=False,
        label="Pathogen CSV",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )
    sequences = forms.FileField(
        required=False,
        label="Sequences CSV",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    # Excel option - one file containing all sheets
    excel_file = forms.FileField(
        required=False,
        label="Excel File",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        file_type = cleaned_data.get("file_type")

        if file_type == "csv":
            # Ensure all CSVs are uploaded
            if not all(
                [
                    cleaned_data.get("inclusion_full_text"),
                    cleaned_data.get("descriptive"),
                    cleaned_data.get("host"),
                    cleaned_data.get("pathogen"),
                    cleaned_data.get("sequences"),
                ]
            ):
                raise forms.ValidationError("Please upload all five CSV files.")

        elif file_type == "excel":
            if not cleaned_data.get("excel_file"):
                raise forms.ValidationError("Please upload an Excel file.")

        return cleaned_data
