class Action:
    """
    Описывает запрос в ArcGIS REST API.
    
    method: тип запроса (query, addFeatures, updateFeatures, deleteFeatures, metadata)
    layer: имя слоя, к которому применяется действие
    attributes: параметры запроса (например, where=id=1)
    bbox: ограничивающий прямоугольник для пространственного фильтра
    max_features: ограничение на количество возвращаемых объектов
    features: список объектов для добавления/обновления/удаления (dict)
    """

    def __init__(self, method=None, layer=None):
        self.method = method  # 'query', 'addFeatures', 'updateFeatures', 'deleteFeatures', 'metadata'
        self.layer = layer  # Имя слоя
        self.attributes = {}  # Параметры запроса (например, where=id=1)
        self.bbox = None  # Ограничивающий прямоугольник [xmin, ymin, xmax, ymax]
        self.max_features = None  # Ограничение на число записей
        self.features = []  # Список объектов для изменения (dict)

    def __repr__(self):
        return f"Action(method={self.method}, layer={self.layer}, attributes={self.attributes}, bbox={self.bbox})"
