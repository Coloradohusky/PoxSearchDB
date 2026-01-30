from rest_framework import serializers

from .models import FullText, Descriptive, Host, Pathogen, Sequence

class FullTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = FullText
        fields = '__all__'

class DescriptiveSerializer(serializers.ModelSerializer):
    full_text = FullTextSerializer(read_only=True)

    class Meta:
        model = Descriptive
        fields = '__all__'

class HostSerializer(serializers.ModelSerializer):
    study = DescriptiveSerializer(read_only=True)

    class Meta:
        model = Host
        fields = '__all__'

class PathogenSerializer(serializers.ModelSerializer):
    associated_host_record = HostSerializer(read_only=True)

    class Meta:
        model = Pathogen
        fields = '__all__'

class SequenceSerializer(serializers.ModelSerializer):
    associated_pathogen_record = PathogenSerializer(read_only=True)
    associated_host_record = HostSerializer(read_only=True)
    study = DescriptiveSerializer(read_only=True)

    class Meta:
        model = Sequence
        fields = '__all__'

class AutoFlattenSerializer(serializers.Serializer):
    """
    Dynamically flattens any Django model instance into a flat dictionary.
    Works with any model, not just Pathogen.
    """
    def to_representation(self, instance):
        flat = {}

        def flatten(prefix, obj):
            if obj is None:
                return
            for field in obj._meta.get_fields():
                # Skip reverse and M2M relationships
                if field.one_to_many or field.many_to_many:
                    continue
                value = getattr(obj, field.name, None)
                if hasattr(value, "_meta"):  # follow FK chain
                    flatten(f"{prefix}{field.name}__", value)
                else:
                    flat[f"{prefix}{field.name}"] = (
                        str(value) if value is not None else ""
                    )

        flatten("", instance)
        return flat
