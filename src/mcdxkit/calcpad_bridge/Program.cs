using System.Text.Json;
using Calcpad.Core;
try {
    var input = JsonDocument.Parse(Console.In.ReadToEnd());
    var parser = new ExpressionParser {
        // CalcpadCE only records hidden/visible errors in Errors when Debug is true.
        Debug = true,
        Settings = new Settings { Math = new MathSettings { Decimals = 12, Degrees = 1 } }
    };
    parser.Parse(input.RootElement.GetProperty("source").GetString()!, true, false);
    Console.Write(JsonSerializer.Serialize(new {html = parser.HtmlResult, errors = parser.Errors}));
    return parser.Errors?.Count > 0 ? 1 : 0;
} catch (Exception e) {
    Console.Error.WriteLine(e.Message);
    return 2;
}
